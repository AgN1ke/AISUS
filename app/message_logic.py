from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field, replace as _dc_replace
from typing import Any

from adapters.base import MessageGeometry, UnifiedMessage
from agent.planner import PlannerInput, plan_message
from agent.runner import run_search, run_simple
from app.chat_geometry import (
    append_reply_chain_lines,
    render_turn_context_messages,
    resolve_message_geometry,
)
from billing import commands as billing_commands
from billing import policy as billing_policy
from billing.bootstrap import begin_turn, end_turn
from billing.context import BillingContext
from billing.runtime import use_billing_context
from app.podcast_dossier import build_podcast_dossier
from app.podcast_intent import (
    build_podcast_pending_request,
    is_explicit_podcast_request,
    parse_podcast_confirmation,
    render_podcast_confirmation,
)
from core.env import chat_join_password
from core.podcast import podcast_runtime_ready
from core.prompts import MEDIA_DEFAULT_TASK_PROMPT, VOICE_REPLY_STYLE_PROMPT
from core.telegram_formatting import render_telegram_html
from db.memory_repository import fetch_recent
from db.settings_repository import (
    clear_podcast_dossier,
    clear_podcast_pending,
    get_podcast_pending,
    get_settings,
    set_podcast_dossier,
    set_podcast_pending,
    upsert_settings,
)
from media.router import handle_ptb_mention, handle_telethon_mention
from media.album_registry import (
    ALBUM_PROCESSING_SETTLE_SECONDS,
    _album_items_for,
    claim_album_processing,
    finish_album_processing,
    observe_album_message,
)
from media.voice import send_voice_response
from memory import memory_manager

logger = logging.getLogger(__name__)

SEARCH_HINT_PATTERNS = (
    r"\bпошукай\b",
    r"\bпогугли\b",
    r"\bзагугли\b",
    r"\bщо нового\b",
    r"\bновини\b",
    r"\bперевір\b",
)


@dataclass
class SessionState:
    chat_id: int
    authed: bool
    mode: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccessResult:
    allowed: bool
    should_stop: bool
    session_state: SessionState
    response_text: str | None = None
    deny_reason: str | None = None


@dataclass
class UserTask:
    instruction: str
    has_media_target: bool
    media_type: str | None = None
    media_context: str | None = None
    needs_search_hint: bool = False
    is_instruction_on_target: bool = False
    target_message_id: int | None = None
    target_message_text: str = ""
    turn_context_msgs: list[dict[str, str]] = field(default_factory=list)
    should_store_user_message: bool = False
    respond_with_voice: bool = False
    voice_command: str | None = None
    voice_command_text: str = ""


@dataclass
class ExecutionPlan:
    route: str
    capability: str
    use_reasoning: bool
    planner_source: str
    notes: str = ""


@dataclass
class ExecutionResult:
    text: str
    route: str
    capability: str


def _should_use_media_route(geometry: MessageGeometry) -> bool:
    return bool(geometry.addressed and geometry.target_media_kind)


def _trace_id(msg: UnifiedMessage) -> str:
    return f"{msg.platform}:{msg.chat_id}:{msg.message_id}"


def _participant_label(participant) -> str:
    if participant is None:
        return ""
    bits = []
    display_name = (getattr(participant, "display_name", None) or "").strip()
    username = (getattr(participant, "username", None) or "").strip()
    if display_name:
        bits.append(display_name)
    if username:
        bits.append(f"@{username}")
    if bits:
        return " ".join(bits).strip()
    user_id = getattr(participant, "user_id", None)
    return str(user_id or "").strip()


def _parse_structured_system_fields(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in (content or "").splitlines()[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _raw_text(msg: UnifiedMessage) -> str:
    return (msg.text or msg.caption or "") or ""


def _session_state(chat_id: int, settings: dict[str, Any] | None) -> SessionState:
    st = settings or {}
    return SessionState(
        chat_id=chat_id,
        authed=bool(st.get("auth_ok") or 0),
        mode=st.get("mode"),
        settings=st,
    )


def _password_candidate(
    text: str,
    geometry: MessageGeometry,
    bot_username: str,
) -> str:
    stripped = (
        geometry.clean_text
        or re.sub(
            rf"@{re.escape(bot_username)}",
            "",
            text,
            flags=re.I,
        ).strip()
    )
    return stripped.split()[0] if stripped else ""


def _auth_prompt(chat_type: str | None, bot_username: str) -> str:
    if chat_type == "private":
        return "🔒 Напиши пароль."
    return f"🔒 Напиши: @{bot_username} <пароль> або дай відповідь на моє повідомлення."


def _needs_search_hint(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    return any(re.search(pattern, lowered) for pattern in SEARCH_HINT_PATTERNS)


def _is_clear_context_command(text: str, bot_username: str) -> bool:
    normalized = (text or "").strip()
    username = (bot_username or "").strip().lstrip("@")
    if not normalized or not username:
        return False
    command, _, rest = normalized.partition(" ")
    if rest.strip():
        return False
    return command.lower() == f"/c@{username.lower()}"


def _parse_voice_command(text: str) -> tuple[str | None, str]:
    normalized = (text or "").strip()
    if not normalized.startswith("/"):
        return None, ""
    command, _, rest = normalized.partition(" ")
    command = command.strip().lower()
    if command == "/a":
        return "speak_text", rest.strip()
    if command == "/v":
        return "speak_last_reply", ""
    return None, ""


def _should_reply_with_voice(geometry: MessageGeometry) -> bool:
    return (geometry.current_media_kind or "").strip().lower() in {"voice", "audio"}


async def _find_last_assistant_reply_text(chat_id: int) -> str:
    recent_rows = await fetch_recent(chat_id)
    for row in reversed(recent_rows):
        if (row.get("role") or "").strip().lower() != "assistant":
            continue
        content = (row.get("content") or "").strip()
        if not content:
            continue
        return content
    return ""


def _podcast_unavailable_message() -> str:
    return (
        "Сервіс генерації подкастів зараз не налаштований або не пройшов перевірку доступу. "
        "Поки readiness-check не зелений, я не маю права запускати цей capability."
    )


def _voice_command_error_message(command: str) -> str:
    normalized = (command or "").strip().lower()
    if normalized == "speak_last_reply":
        return (
            "Не зміг надіслати озвучку останнього повідомлення. "
            "Спробуй ще раз трохи пізніше."
        )
    return "Не зміг надіслати озвучку. Спробуй ще раз трохи пізніше."


async def _maybe_handle_podcast_flow(
    msg: UnifiedMessage,
    task: UserTask,
) -> str | None:
    decision, extra_style = parse_podcast_confirmation(task.instruction)
    explicit_request = is_explicit_podcast_request(task.instruction)
    if decision == "none" and not explicit_request:
        return None
    pending = await get_podcast_pending(msg.chat_id)
    if pending and decision == "cancel":
        await clear_podcast_pending(msg.chat_id)
        logger.info("podcast.pending_cancelled chat_id=%s", msg.chat_id)
        return "Добре, запит на подкаст скасовано."
    if pending and decision == "confirm":
        await clear_podcast_pending(msg.chat_id)
        if not podcast_runtime_ready():
            logger.info("podcast.confirm_but_unavailable chat_id=%s", msg.chat_id)
            return _podcast_unavailable_message()
        topic = str(pending.get("topic_label") or "цю тему").strip()
        style_bits = [str(pending.get("style_instruction") or "").strip(), extra_style.strip()]
        merged_style = " ".join(bit for bit in style_bits if bit).strip()
        pending = dict(pending)
        pending["style_instruction"] = merged_style
        try:
            dossier = await build_podcast_dossier(msg.chat_id, pending)
            await set_podcast_dossier(msg.chat_id, dossier.to_dict())
        except Exception as exc:
            logger.exception(
                "podcast.dossier_build_failed chat_id=%s error=%s",
                msg.chat_id,
                exc,
            )
            return (
                "Тему я підтвердив, але на етапі збирання матеріалу для подкасту сталася помилка. "
                "Потрібно виправити dossier-builder, перш ніж рухатися далі."
            )
        logger.info(
            "podcast.confirmed chat_id=%s topic=%s style_len=%s dossier_turns=%s core=%s long=%s",
            msg.chat_id,
            topic[:120],
            len(merged_style),
            len(dossier.recent_turns),
            len(dossier.core_facts),
            len(dossier.long_memory_notes),
        )
        style_line = (
            f"\n\nДодатковий формат зафіксував: <i>{merged_style}</i>."
            if merged_style
            else ""
        )
        return (
            f"Підтвердження теми прийняв: <b>{topic}</b>."
            f"{style_line}\n\n"
            "Я вже зібрав початковий dossier по цій темі: підтягнув релевантний зріз розмови, "
            "окремі акценти користувача і пам'ять по темі. Наступним етапом буде перетворення "
            "цього dossier у payload для NotebookLM Podcast API і реальний виклик зовнішнього job."
        )

    if not explicit_request:
        return None
    if not podcast_runtime_ready():
        logger.info("podcast.request_unavailable chat_id=%s", msg.chat_id)
        return _podcast_unavailable_message()

    try:
        recent_rows = await fetch_recent(msg.chat_id, limit=12)
    except Exception:
        recent_rows = []
    pending_request = build_podcast_pending_request(task, recent_rows)
    await clear_podcast_dossier(msg.chat_id)
    await set_podcast_pending(msg.chat_id, pending_request.to_dict())
    logger.info(
        "podcast.pending_created chat_id=%s topic=%s scope=%s",
        msg.chat_id,
        pending_request.topic_label[:120],
        pending_request.source_scope,
    )
    return render_podcast_confirmation(pending_request)


async def check_access(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    session_state: SessionState,
) -> AccessResult:
    trace = _trace_id(msg)
    text = _raw_text(msg)
    bot_username = msg.bot_username or ""

    if session_state.authed:
        if not geometry.addressed:
            logger.info("flow.ignore_authed trace=%s reason=not_addressed", trace)
            return AccessResult(
                allowed=False,
                should_stop=True,
                session_state=session_state,
                deny_reason="not_addressed",
            )
        return AccessResult(
            allowed=True,
            should_stop=False,
            session_state=session_state,
        )

    if not geometry.addressed:
        logger.info("flow.ignore_unauthed trace=%s reason=not_addressed", trace)
        return AccessResult(
            allowed=False,
            should_stop=True,
            session_state=session_state,
            deny_reason="not_addressed",
        )

    password = _password_candidate(text, geometry, bot_username)
    if password and password == chat_join_password():
        logger.info("flow.auth_success trace=%s", trace)
        mode = "userbot" if msg.platform == "telethon" else "bot"
        await upsert_settings(
            msg.chat_id,
            auth_ok=True,
            mode=mode,
        )
        return AccessResult(
            allowed=False,
            should_stop=True,
            session_state=SessionState(
                chat_id=msg.chat_id,
                authed=True,
                mode=mode,
                settings={**session_state.settings, "auth_ok": True, "mode": mode},
            ),
            response_text="✅ Пароль прийнято. Я готова працювати тут.",
        )

    logger.info(
        "flow.auth_prompt trace=%s provided_password=%s",
        trace,
        bool(password),
    )
    return AccessResult(
        allowed=False,
        should_stop=True,
        session_state=session_state,
        response_text=_auth_prompt(geometry.chat_type, bot_username),
        deny_reason="auth_required",
    )


async def _resolve_media_instruction(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
) -> tuple[str | None, str | None]:
    if not _should_use_media_route(geometry):
        return None, None

    trace = _trace_id(msg)
    bot_username = msg.bot_username or ""
    logger.info(
        "flow.mention_route trace=%s platform=%s mentioned=%s reply_to_bot=%s target_media=%s",
        trace,
        msg.platform,
        geometry.addressed_via_mention,
        geometry.reply_to_bot,
        geometry.target_media_kind or "",
    )

    if msg.platform == "ptb":
        context = getattr(msg.raw_update, "_bot", None)
        user_text, route_kind = await handle_ptb_mention(
            msg.raw_update, context, bot_username
        )
    else:
        user_text, route_kind = await handle_telethon_mention(
            msg.raw_update, bot_username
        )

    logger.info(
        "flow.mention_route_done trace=%s user_text_len=%s media_kind=%s route_kind=%s",
        trace,
        len(user_text or ""),
        geometry.target_media_kind or "",
        route_kind or "",
    )
    return user_text, ((route_kind or "").strip() or None)


async def _build_participant_history_context(
    chat_id: int,
    geometry: MessageGeometry,
) -> dict[str, str] | None:
    sender = _participant_label(geometry.sender).strip()
    if not sender:
        return None
    try:
        recent_rows = await fetch_recent(chat_id, limit=40)
    except Exception:
        return None

    matched_turns: list[dict[str, str]] = []
    for row in recent_rows:
        if (row.get("role") or "").strip().lower() != "system":
            continue
        content = (row.get("content") or "").strip()
        if not content.startswith("[CHAT-TURN]"):
            continue
        fields = _parse_structured_system_fields(content)
        if (fields.get("sender") or "").strip() != sender:
            continue
        matched_turns.append(fields)

    if not matched_turns:
        return None

    lines = ["[PARTICIPANT-HISTORY]", f"current_sender: {sender}"]
    if geometry.message_sent_at_local:
        lines.append(f"current_message_time_local: {geometry.message_sent_at_local}")
    if geometry.message_sent_at_utc:
        lines.append(f"current_message_time_utc: {geometry.message_sent_at_utc}")
    reply_author = _participant_label(geometry.reply_target.author).strip()
    if reply_author:
        lines.append(f"current_reply_target_author: {reply_author}")
    lines.append("recent_same_sender_turns:")

    for fields in matched_turns[-4:]:
        when = (
            fields.get("current_message_time_local")
            or fields.get("current_message_time_utc")
            or "unknown_time"
        )
        text = (
            fields.get("resolved_instruction")
            or fields.get("current_user_text")
            or fields.get("reply_target_text")
            or ""
        ).strip()
        if not text:
            continue
        lines.append(f"- {when} | {text[:240]}")

    if lines[-1] == "recent_same_sender_turns:":
        return None
    return {"role": "system", "content": "\n".join(lines)}


def _message_id_set_from_fields(fields: dict[str, str]) -> set[int]:
    ids: set[int] = set()
    for key, value in fields.items():
        if not value:
            continue
        if key in {"current_message_id", "reply_target_message_id"} or re.match(
            r"reply_chain_hop_\d+_message_id$",
            key,
        ):
            try:
                ids.add(int(value))
            except Exception:
                continue
    return ids


def _geometry_thread_anchor_ids(geometry: MessageGeometry) -> set[int]:
    ids: set[int] = set()
    if geometry.current_message_id is not None:
        ids.add(int(geometry.current_message_id))
    if geometry.reply_target.message_id is not None:
        ids.add(int(geometry.reply_target.message_id))
    for hop in geometry.reply_chain:
        if hop.message_id is not None:
            ids.add(int(hop.message_id))
    return ids


def _final_turn_text(fields: dict[str, str]) -> str:
    return (
        (fields.get("resolved_instruction") or "").strip()
        or (fields.get("current_user_text") or "").strip()
        or (fields.get("reply_target_text") or "").strip()
    )


def _recent_turn_bundles(recent_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in recent_rows:
        role = (row.get("role") or "").strip().lower()
        content = (row.get("content") or "").strip()
        if role == "system" and content.startswith("[CHAT-TURN]"):
            if current is not None:
                bundles.append(current)
            fields = _parse_structured_system_fields(content)
            current = {
                "fields": fields,
                "assistant_replies": [],
                "user_messages": [],
            }
            continue
        if current is None:
            continue
        if role == "assistant" and content:
            current["assistant_replies"].append(content)
        elif role == "user" and content:
            current["user_messages"].append(content)
    if current is not None:
        bundles.append(current)
    return bundles


def _thread_match_mode(
    geometry: MessageGeometry,
    candidate_fields: dict[str, str],
) -> str | None:
    anchor_ids = _geometry_thread_anchor_ids(geometry)
    candidate_ids = _message_id_set_from_fields(candidate_fields)
    if anchor_ids and candidate_ids and anchor_ids.intersection(candidate_ids):
        return "reply_chain_overlap"

    current_sender = _participant_label(geometry.sender).strip()
    candidate_sender = (candidate_fields.get("sender") or "").strip()
    current_reply_author = _participant_label(geometry.reply_target.author).strip()
    candidate_reply_author = (candidate_fields.get("reply_target_author") or "").strip()

    if (
        not geometry.reply_chain
        and not geometry.reply_target.message_id
        and current_sender
        and current_sender == candidate_sender
    ):
        return "same_sender_fallback"

    if (
        current_sender
        and current_reply_author
        and current_sender == candidate_sender
        and current_reply_author == candidate_reply_author
    ):
        return "sender_target_overlap"

    return None


async def _build_thread_history_context(
    chat_id: int,
    geometry: MessageGeometry,
) -> dict[str, str] | None:
    try:
        recent_rows = await fetch_recent(chat_id, limit=60)
    except Exception:
        return None

    bundles = _recent_turn_bundles(recent_rows)
    if not bundles:
        return None

    matched: list[tuple[str, dict[str, Any]]] = []
    for bundle in bundles:
        fields = bundle["fields"]
        mode = _thread_match_mode(geometry, fields)
        if mode:
            matched.append((mode, bundle))

    if not matched:
        return None

    anchor_ids = sorted(_geometry_thread_anchor_ids(geometry))
    lines = ["[THREAD-HISTORY]"]
    if anchor_ids:
        lines.append(
            "thread_anchor_message_ids: " + ", ".join(str(value) for value in anchor_ids)
        )
    current_sender = _participant_label(geometry.sender).strip()
    if current_sender:
        lines.append(f"current_sender: {current_sender}")
    if geometry.message_sent_at_local:
        lines.append(f"current_message_time_local: {geometry.message_sent_at_local}")
    if geometry.message_sent_at_utc:
        lines.append(f"current_message_time_utc: {geometry.message_sent_at_utc}")
    lines.append("recent_thread_turns:")

    for mode, bundle in matched[-4:]:
        fields = bundle["fields"]
        when = (
            (fields.get("current_message_time_local") or "").strip()
            or (fields.get("current_message_time_utc") or "").strip()
            or "unknown_time"
        )
        sender = (fields.get("sender") or "").strip() or "unknown_sender"
        target = (fields.get("reply_target_text") or "").strip()
        instruction = _final_turn_text(fields)
        lines.append(f"- {when} | match={mode} | sender: {sender}")
        if target:
            lines.append(f"  target: {target[:240]}")
        if instruction:
            lines.append(f"  user: {instruction[:240]}")
        assistant_replies = bundle.get("assistant_replies") or []
        if assistant_replies:
            lines.append(f"  assistant: {assistant_replies[-1][:240]}")

    if lines[-1] == "recent_thread_turns:":
        return None
    return {"role": "system", "content": "\n".join(lines)}


async def build_user_task(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    media_instruction: str | None,
    media_type_override: str | None = None,
) -> UserTask | None:
    trace = _trace_id(msg)
    instruction = (media_instruction or "").strip()
    actual_user_text = (geometry.clean_text or "").strip()
    should_store_user_message = bool(actual_user_text)

    if not instruction:
        instruction = (actual_user_text or _raw_text(msg)).strip()
        if not instruction:
            logger.info("flow.ignore_empty trace=%s", trace)
            return None
        logger.info(
            "flow.base_text_ready trace=%s text_len=%s", trace, len(instruction)
        )

    target_message_id = geometry.reply_target.message_id
    target_message_text = geometry.reply_target.text or ""
    voice_command, voice_command_text = _parse_voice_command(actual_user_text)
    turn_context_msgs = render_turn_context_messages(geometry)
    thread_history = await _build_thread_history_context(msg.chat_id, geometry)
    if thread_history:
        turn_context_msgs.append(thread_history)
    participant_history = await _build_participant_history_context(msg.chat_id, geometry)
    if participant_history:
        turn_context_msgs.append(participant_history)
    respond_with_voice = _should_reply_with_voice(geometry)
    if (
        not should_store_user_message
        and (geometry.current_media_kind or "").strip().lower() in {"voice", "audio"}
        and instruction
        and instruction != MEDIA_DEFAULT_TASK_PROMPT
    ):
        should_store_user_message = True
    if respond_with_voice:
        turn_context_msgs.append(
            {"role": "system", "content": VOICE_REPLY_STYLE_PROMPT}
        )
    task = UserTask(
        instruction=instruction,
        has_media_target=bool(geometry.target_media_kind),
        media_type=media_type_override or geometry.target_media_kind,
        media_context=None,
        needs_search_hint=_needs_search_hint(instruction),
        is_instruction_on_target=bool(target_message_id and instruction),
        target_message_id=target_message_id,
        target_message_text=target_message_text,
        turn_context_msgs=turn_context_msgs,
        should_store_user_message=should_store_user_message,
        respond_with_voice=respond_with_voice,
        voice_command=voice_command,
        voice_command_text=voice_command_text,
    )
    logger.info(
        "flow.task_built trace=%s instruction_len=%s media_target=%s media_type=%s search_hint=%s voice_reply=%s voice_command=%s",
        trace,
        len(task.instruction),
        task.has_media_target,
        task.media_type or "",
        task.needs_search_hint,
        task.respond_with_voice,
        task.voice_command or "",
    )
    return task


async def plan_execution(
    chat_id: int,
    task: UserTask,
    geometry: MessageGeometry,
    session_state: SessionState,
) -> ExecutionPlan:
    del session_state  # Reserved for future routing/session policy decisions.

    # Fetch last few messages so the planner sees gradual intent formation.
    dialogue_context: tuple[dict, ...] = ()
    try:
        recent_rows = await fetch_recent(chat_id, limit=6)
        recent_context = tuple(
            {"role": row["role"], "content": row["content"]}
            for row in recent_rows
            if row.get("content")
        )
        dialogue_context = tuple(task.turn_context_msgs) + recent_context
    except Exception:
        dialogue_context = tuple(task.turn_context_msgs)

    decision = await asyncio.to_thread(
        plan_message,
        PlannerInput(
            user_text=task.instruction,
            is_private=geometry.chat_type == "private",
            addressed_via_mention=geometry.addressed_via_mention,
            reply_to_bot=geometry.reply_to_bot,
            has_media_context=task.has_media_target,
            media_kind=task.media_type,
            dialogue_context=dialogue_context,
        ),
    )
    return ExecutionPlan(
        route=decision.route,
        capability=decision.capability,
        use_reasoning=decision.use_reasoning,
        planner_source=decision.planner_source,
        notes=decision.notes,
    )


async def execute_plan(
    chat_id: int,
    task: UserTask,
    plan: ExecutionPlan,
) -> ExecutionResult:
    if plan.route == "search":
        answer = await run_search(
            chat_id,
            task.instruction,
            use_reasoning=plan.use_reasoning,
            turn_context_msgs=task.turn_context_msgs,
        )
    else:
        answer = await run_simple(
            chat_id,
            task.instruction,
            capability=plan.capability,
            use_reasoning=plan.use_reasoning,
            turn_context_msgs=task.turn_context_msgs,
        )
    return ExecutionResult(
        text=(answer or "").strip(),
        route=plan.route,
        capability=plan.capability,
    )


async def send_response(
    msg: UnifiedMessage,
    text: str,
    reply_to: int | None = None,
    *,
    reply_markup: Any | None = None,
) -> None:
    rendered = render_telegram_html(text)
    if msg.platform == "ptb":
        kwargs: dict[str, Any] = {
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to is not None:
            kwargs["reply_to_message_id"] = reply_to
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        await msg.raw_update.effective_message.reply_text(rendered, **kwargs)
        return

    kwargs = {"parse_mode": "html"}
    if reply_to is not None:
        kwargs["reply_to"] = reply_to
    try:
        await msg.raw_update.reply(rendered, link_preview=False, **kwargs)
    except TypeError:
        await msg.raw_update.reply(rendered, **kwargs)


async def _handle_voice_command(
    msg: UnifiedMessage,
    task: UserTask,
) -> str | None:
    command = (task.voice_command or "").strip().lower()
    if command == "speak_text":
        return (task.voice_command_text or "").strip()
    if command != "speak_last_reply":
        return None
    return await _find_last_assistant_reply_text(msg.chat_id)


def _build_chat_turn_memory_event(
    geometry: MessageGeometry,
    task: UserTask,
) -> str:
    lines = ["[CHAT-TURN]"]
    if geometry.chat_type:
        lines.append(f"chat_type: {geometry.chat_type}")
    if geometry.current_message_id is not None:
        lines.append(f"current_message_id: {geometry.current_message_id}")
    if geometry.message_sent_at_local:
        lines.append(f"current_message_time_local: {geometry.message_sent_at_local}")
    if geometry.message_sent_at_utc:
        lines.append(f"current_message_time_utc: {geometry.message_sent_at_utc}")
    sender = _participant_label(geometry.sender)
    if sender:
        lines.append(f"sender: {sender}")
    if geometry.addressed_via_mention:
        lines.append("addressed_via_mention: true")
    if geometry.reply_to_bot:
        lines.append("reply_to_bot: true")
    if geometry.current_media_kind:
        lines.append(f"current_media_kind: {geometry.current_media_kind}")
    if geometry.target_media_kind:
        lines.append(f"target_media_kind: {geometry.target_media_kind}")
    if task.target_message_id is not None:
        lines.append(f"reply_target_message_id: {task.target_message_id}")
    if geometry.reply_target.sent_at_local:
        lines.append(f"reply_target_time_local: {geometry.reply_target.sent_at_local}")
    if geometry.reply_target.sent_at_utc:
        lines.append(f"reply_target_time_utc: {geometry.reply_target.sent_at_utc}")
    reply_author = _participant_label(geometry.reply_target.author)
    if reply_author:
        lines.append(f"reply_target_author: {reply_author}")
    if geometry.reply_target.media_kind:
        lines.append(f"reply_target_media_kind: {geometry.reply_target.media_kind}")
    if task.target_message_text:
        lines.append(f"reply_target_text: {task.target_message_text[:1200]}")
    append_reply_chain_lines(lines, geometry.reply_chain)
    if geometry.clean_text:
        lines.append(f"current_user_text: {geometry.clean_text[:1200]}")
    if task.instruction and task.instruction != geometry.clean_text:
        lines.append(f"resolved_instruction: {task.instruction[:1200]}")
    return "\n".join(lines)


async def _append_user_task(
    chat_id: int,
    task: UserTask,
    geometry: MessageGeometry,
) -> None:
    turn_event = _build_chat_turn_memory_event(geometry, task)
    await memory_manager.append_message(chat_id, "system", turn_event)
    if not task.should_store_user_message:
        await memory_manager.ensure_budget(chat_id)
        return
    user_message = (geometry.clean_text or task.instruction).strip()
    await memory_manager.append_message(chat_id, "user", user_message)
    await memory_manager.ensure_budget(chat_id)


async def _append_assistant_reply(chat_id: int, text: str) -> None:
    await memory_manager.append_message(chat_id, "assistant", text)
    await memory_manager.ensure_budget(chat_id)


async def process_message(msg: UnifiedMessage) -> None:
    trace = _trace_id(msg)
    observe_album_message(msg)
    geometry = await resolve_message_geometry(msg)
    msg.geometry = geometry
    session_state = _session_state(msg.chat_id, await get_settings(msg.chat_id) or {})

    sender = geometry.sender
    sender_user_id = getattr(sender, "user_id", None)
    user_text_preview = (geometry.clean_text or msg.text or msg.caption or "")[:2000]
    try:
        billing_ctx = await begin_turn(
            chat_id=msg.chat_id,
            user_id=sender_user_id,
            tg_chat_type=geometry.chat_type,
            tg_username=getattr(sender, "username", None),
            first_name=getattr(sender, "display_name", None),
            tg_message_id=msg.message_id,
            user_message_text=user_text_preview,
        )
    except Exception as exc:
        logger.warning("billing.begin_turn_failed trace=%s: %s", trace, exc)
        billing_ctx = None

    if billing_ctx is not None:
        try:
            assigned = await billing_policy.assign_owner_if_unassigned(
                msg.chat_id, billing_ctx.account_id
            )
            if assigned:
                logger.info(
                    "billing.owner_assigned trace=%s chat_id=%s account_id=%s",
                    trace,
                    msg.chat_id,
                    billing_ctx.account_id,
                )
        except Exception as exc:
            logger.warning(
                "billing.assign_owner_failed trace=%s: %s", trace, exc
            )

    finalize_state: dict[str, Any] = {
        "status": "completed",
        "route": None,
        "capability": None,
    }
    try:
        async with use_billing_context(billing_ctx):
            await _handle_message_inner(
                msg=msg,
                trace=trace,
                geometry=geometry,
                session_state=session_state,
                billing_ctx=billing_ctx,
                user_text_preview=user_text_preview,
                finalize_state=finalize_state,
            )
    except Exception:
        finalize_state["status"] = "failed"
        raise
    finally:
        await end_turn(billing_ctx, **finalize_state)


async def _enforce_multitenant_policy(
    *,
    msg: UnifiedMessage,
    trace: str,
    geometry: MessageGeometry,
    billing_ctx: BillingContext | None,
    user_text_preview: str,
    finalize_state: dict[str, Any],
) -> bool:
    """Run multitenant access + budget gates. Returns False if blocked.

    When the turn has no billing context (no resolvable account) we skip the
    gate entirely — the legacy single-tenant flow still needs to work during
    rollout. Stage 4 onboarding will tighten this.
    """
    if billing_ctx is None:
        return True

    sender = geometry.sender
    sender_user_id = getattr(sender, "user_id", None) or billing_ctx.user_id

    access_decision = await billing_policy.check_chat_access(
        chat_id=msg.chat_id,
        user_id=int(sender_user_id),
        account_id=billing_ctx.account_id,
    )
    if not access_decision.allowed:
        logger.info(
            "policy.access_blocked trace=%s reason=%s message=%s",
            trace,
            access_decision.reason,
            bool(access_decision.message),
        )
        if access_decision.message:
            await send_response(msg, access_decision.message)
        finalize_state["status"] = "policy_blocked"
        return False

    estimated = await billing_policy.estimate_message_cost(
        text=user_text_preview,
        capability="chat_final",
    )
    budget_decision = await billing_policy.check_budget(
        account_id=billing_ctx.account_id,
        chat_id=msg.chat_id,
        user_id=billing_ctx.user_id,
        estimated_uah=estimated,
    )
    if not budget_decision.allowed:
        logger.info(
            "policy.budget_blocked trace=%s reason=%s est_uah=%s avail_uah=%s",
            trace,
            budget_decision.reason,
            budget_decision.estimated_uah,
            budget_decision.available_uah,
        )
        if budget_decision.message:
            await send_response(msg, budget_decision.message)
        finalize_state["status"] = "budget_blocked"
        return False

    return True


async def _handle_message_inner(
    *,
    msg: UnifiedMessage,
    trace: str,
    geometry: MessageGeometry,
    session_state: SessionState,
    billing_ctx: BillingContext | None,
    user_text_preview: str,
    finalize_state: dict[str, Any],
) -> None:
    album_claimed = False
    logger.info(
        "flow.start trace=%s text_len=%s has_photo=%s has_voice=%s has_video=%s has_document=%s",
        trace,
        len(_raw_text(msg)),
        msg.has_photo,
        msg.has_voice,
        msg.has_video,
        msg.has_document,
    )
    logger.info(
        "flow.classified trace=%s authed=%s private=%s mentioned=%s reply_to_bot=%s addressed=%s current_media=%s target_media=%s",
        trace,
        session_state.authed,
        geometry.chat_type == "private",
        geometry.addressed_via_mention,
        geometry.reply_to_bot,
        geometry.addressed,
        geometry.current_media_kind or "",
        geometry.target_media_kind or "",
    )
    logger.info(
        "flow.geometry trace=%s sender=%s msg_time=%s reply_target_author=%s reply_target_id=%s reply_target_time=%s reply_target_text_len=%s clean_text_len=%s",
        trace,
        _participant_label(geometry.sender) or "",
        geometry.message_sent_at_local or "",
        _participant_label(geometry.reply_target.author) or "",
        geometry.reply_target.message_id,
        geometry.reply_target.sent_at_local or "",
        len(geometry.reply_target.text or ""),
        len(geometry.clean_text or ""),
    )

    command_result = await billing_commands.try_handle_command(
        msg=msg,
        geometry=geometry,
        billing_ctx=billing_ctx,
    )
    if command_result is not None:
        finalize_state["status"] = command_result.finalize_status
        finalize_state["route"] = command_result.route
        finalize_state["capability"] = command_result.capability
        if command_result.response_text:
            await send_response(
                msg,
                command_result.response_text,
                reply_markup=command_result.response_markup,
            )
        logger.info(
            "flow.command_handled trace=%s capability=%s status=%s",
            trace,
            command_result.capability,
            command_result.finalize_status,
        )
        return

    access = await check_access(msg, geometry, session_state)
    if access.should_stop:
        if access.response_text:
            await send_response(msg, access.response_text)
        return

    policy_ok = await _enforce_multitenant_policy(
        msg=msg,
        trace=trace,
        geometry=geometry,
        billing_ctx=billing_ctx,
        user_text_preview=user_text_preview,
        finalize_state=finalize_state,
    )
    if not policy_ok:
        return

    if msg.media_group_id:
        # Every album member must go through the album gate — either claim
        # processing or be silently dropped.  Never let an album item fall
        # through to the regular text pipeline (that causes N replies).
        album_claimed = claim_album_processing(msg)
        if not album_claimed:
            logger.info(
                "flow.album_skip_duplicate trace=%s group_id=%s message_id=%s",
                trace,
                msg.media_group_id,
                msg.message_id,
            )
            return
        logger.info(
            "flow.album_claimed trace=%s group_id=%s settle=%.1f",
            trace,
            msg.media_group_id,
            ALBUM_PROCESSING_SETTLE_SECONDS,
        )
        await asyncio.sleep(ALBUM_PROCESSING_SETTLE_SECONDS)
        # After settle, check if the album is addressed.  The claiming
        # message may not be the one with the @mention / caption, so also
        # check text from all collected album items.
        album_items = _album_items_for(
            msg.platform, int(msg.chat_id), msg.media_group_id,
        )
        album_has_text = any(
            (item.text or "").strip() for item in album_items
        )
        if not geometry.addressed and not album_has_text:
            logger.info(
                "flow.album_not_addressed trace=%s group_id=%s",
                trace,
                msg.media_group_id,
            )
            finish_album_processing(msg, handled=False)
            return
        # In private chats the album is always addressed.  In group chats
        # the presence of any text/caption in the album implies intent
        # (the user typed something alongside the media).
        if not geometry.addressed and album_has_text:
            # Promote to addressed — user attached text to this album.
            album_text = geometry.clean_text or next(
                (item.text for item in album_items if (item.text or "").strip()), ""
            )
            geometry = _dc_replace(
                geometry,
                addressed=True,
                clean_text=album_text,
                target_media_kind=geometry.current_media_kind or geometry.target_media_kind,
            )
            msg.geometry = geometry

    if _is_clear_context_command(_raw_text(msg), msg.bot_username or ""):
        await memory_manager.clear_all(msg.chat_id)
        await clear_podcast_pending(msg.chat_id)
        await clear_podcast_dossier(msg.chat_id)
        logger.info("flow.memory_cleared trace=%s chat_id=%s", trace, msg.chat_id)
        await send_response(
            msg,
            "Контекст цього чату повністю очищено. Починаємо з нуля.",
        )
        return

    media_instruction, media_type_override = await _resolve_media_instruction(msg, geometry)
    task = await build_user_task(msg, geometry, media_instruction, media_type_override=media_type_override)
    if task is None:
        if album_claimed:
            finish_album_processing(msg, handled=False)
        return

    await _append_user_task(msg.chat_id, task, geometry)
    if task.voice_command:
        voice_text = await _handle_voice_command(msg, task)
        if not voice_text:
            fallback = (
                "Немає попереднього повідомлення бота для цього чату."
                if task.voice_command == "speak_last_reply"
                else "Немає тексту для озвучення."
            )
            await send_response(msg, fallback)
            await _append_assistant_reply(msg.chat_id, fallback)
            if album_claimed:
                finish_album_processing(msg, handled=True)
            return
        logger.info(
            "flow.voice_command trace=%s command=%s text_len=%s",
            trace,
            task.voice_command,
            len(voice_text),
        )
        try:
            await send_voice_response(msg, voice_text)
        except Exception as exc:
            logger.error(
                "flow.voice_command_failed trace=%s command=%s error=%s",
                trace,
                task.voice_command,
                exc,
                exc_info=True,
            )
            fallback_text = _voice_command_error_message(task.voice_command or "")
            await send_response(msg, fallback_text)
            logger.info("flow.voice_command_fallback_notice trace=%s", trace)
            await _append_assistant_reply(msg.chat_id, fallback_text)
            if album_claimed:
                finish_album_processing(msg, handled=True)
            return
        await _append_assistant_reply(msg.chat_id, voice_text)
        logger.info("flow.voice_command_sent trace=%s", trace)
        if album_claimed:
            finish_album_processing(msg, handled=True)
        return
    podcast_response = await _maybe_handle_podcast_flow(msg, task)
    if podcast_response:
        await send_response(msg, podcast_response)
        await _append_assistant_reply(msg.chat_id, podcast_response)
        logger.info("flow.podcast_handled trace=%s", trace)
        if album_claimed:
            finish_album_processing(msg, handled=True)
        return
    plan = await plan_execution(msg.chat_id, task, geometry, access.session_state)
    finalize_state["route"] = plan.route
    finalize_state["capability"] = plan.capability
    logger.info(
        "flow.planner_decision trace=%s route=%s capability=%s source=%s reasoning=%s text_len=%s",
        trace,
        plan.route,
        plan.capability,
        plan.planner_source,
        plan.use_reasoning,
        len(task.instruction or ""),
    )
    logger.info(
        "flow.execute trace=%s route=%s capability=%s turn_context=%s voice_reply=%s",
        trace,
        plan.route,
        plan.capability,
        len(task.turn_context_msgs),
        task.respond_with_voice,
    )

    result = await execute_plan(msg.chat_id, task, plan)
    if not result.text:
        logger.warning("flow.empty_answer trace=%s", trace)
        if album_claimed:
            finish_album_processing(msg, handled=False)
        return

    logger.info("flow.reply_ready trace=%s answer_len=%s", trace, len(result.text))
    if task.respond_with_voice:
        try:
            await send_voice_response(msg, result.text)
            logger.info(
                "flow.voice_reply_sent trace=%s platform=%s", trace, msg.platform
            )
        except Exception as exc:
            logger.error(
                "flow.voice_reply_failed trace=%s error=%s",
                trace,
                exc,
                exc_info=True,
            )
            await send_response(msg, result.text)
            logger.info(
                "flow.voice_reply_fallback_text trace=%s platform=%s",
                trace,
                msg.platform,
            )
    else:
        await send_response(msg, result.text)
        logger.info("flow.reply_sent trace=%s platform=%s", trace, msg.platform)
    await _append_assistant_reply(msg.chat_id, result.text)
    logger.info("flow.done trace=%s", trace)
    if album_claimed:
        finish_album_processing(msg, handled=True)
