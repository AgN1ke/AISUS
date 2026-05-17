from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import replace as _dc_replace
from dataclasses import dataclass, field
from typing import Any

from adapters.base import MessageGeometry, UnifiedMessage
from agent.planner import PlannerInput, plan_message
from agent.runner import run_search, run_simple
from app.chat_geometry import render_turn_context_messages, resolve_message_geometry
from core.env import chat_join_password
from core.telegram_formatting import render_telegram_html
from db.memory_repository import fetch_recent
from db.settings_repository import get_settings, upsert_settings
from media.album_registry import (
    ALBUM_PROCESSING_SETTLE_SECONDS,
    _album_items_for,
    claim_album_processing,
    finish_album_processing,
    observe_album_message,
)
from media.router import handle_ptb_mention, handle_telethon_mention
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

# Debug-маркери видимі користувачу — щоб ми могли перевірити, що capability
# справді задіяна (без них «вмикнувся reasoning чи ні» — невидимо).
SEARCH_PERFORMED_MARKER = "⚠️УВАГА! ВІДБУВСЯ ПОШУК!⚠️"
REASONING_MARKER = "🧠 [reasoning ON]"
MESSAGE_DEDUPE_TTL_SECONDS = 10 * 60
_RECENT_MESSAGE_KEYS: dict[tuple[str, int, int], float] = {}
_FAKE_SEARCH_BLOCK_RE = re.compile(r"^\s*\[SEARCH\][\s\S]{0,2000}?\[/SEARCH\]", re.I)


def _looks_like_fake_search_block(text: str) -> bool:
    return bool(_FAKE_SEARCH_BLOCK_RE.search(text or ""))


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


def _raw_text(msg: UnifiedMessage) -> str:
    return (msg.text or msg.caption or "") or ""


def _claim_message_once(msg: UnifiedMessage) -> bool:
    now = time.monotonic()
    cutoff = now - MESSAGE_DEDUPE_TTL_SECONDS
    stale = [key for key, ts in _RECENT_MESSAGE_KEYS.items() if ts < cutoff]
    for key in stale:
        _RECENT_MESSAGE_KEYS.pop(key, None)

    key = (msg.platform, int(msg.chat_id), int(msg.message_id))
    if key in _RECENT_MESSAGE_KEYS:
        return False
    _RECENT_MESSAGE_KEYS[key] = now
    return True


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


_VOICE_CMD_RE = re.compile(
    r"^/(a|v)(?:@(\w+))?(?:\s+(.*))?$",
    re.IGNORECASE | re.DOTALL,
)


def _should_reply_with_voice(geometry: MessageGeometry) -> bool:
    """If user spoke voice/audio → bot replies via voice (B-026)."""
    return (geometry.current_media_kind or "").strip().lower() in {"voice", "audio"}


def _parse_voice_command(text: str, bot_username: str) -> tuple[str | None, str, bool]:
    """Parse /a or /v slash command.

    Returns (command, payload, addressed_to_us) where:
    - command: 'speak_text' for /a, 'speak_last' for /v, None if not voice cmd
    - payload: the text after /a (empty for /v)
    - addressed_to_us: True if bare in private OR explicitly tagged @bot_username
    """
    raw = (text or "").strip()
    if not raw or not raw.startswith("/"):
        return None, "", False
    match = _VOICE_CMD_RE.match(raw)
    if not match:
        return None, "", False
    cmd_letter = match.group(1).lower()
    tagged_username = (match.group(2) or "").strip().lower()
    payload = (match.group(3) or "").strip()

    bot_username_lower = (bot_username or "").strip().lower()
    if tagged_username:
        if tagged_username != bot_username_lower:
            return None, "", False
        addressed = True
    else:
        # bare /a or /v — addressed only in private (caller decides via chat_type)
        addressed = True  # caller filters by chat_type

    if cmd_letter == "a":
        return "speak_text", payload, addressed
    if cmd_letter == "v":
        return "speak_last", payload, addressed
    return None, "", False


def _voice_command_error_message(command: str) -> str:
    if command == "speak_last":
        return "⚠️ Не зміг знайти останню текстову відповідь для озвучення."
    return "⚠️ Не зміг озвучити повідомлення. Спробуй ще раз."


async def _find_last_assistant_reply_text(chat_id: int) -> str:
    """Scan recent memory backwards for last assistant text message."""
    rows = await fetch_recent(chat_id) or []
    for row in reversed(rows):
        if (row.get("role") or "").lower() == "assistant":
            content = (row.get("content") or "").strip()
            if content:
                return content
    return ""


def _is_clear_context_command(
    text: str, bot_username: str, *, chat_type: str | None = None
) -> bool:
    """Detect /c clear command.

    Group/supergroup: require strict /c@bot_username form (multi-bot safety —
    bare /c must not wipe memory of every bot in the chat). Form '@bot /c'
    (mention before command) is also rejected — only suffix tag works.

    Private: bare /c is allowed (only one bot in the conversation).
    """
    normalized = (text or "").strip()
    if not normalized:
        return False
    command, _, rest = normalized.partition(" ")
    if rest.strip():
        return False
    command = command.lower()
    username = (bot_username or "").strip().lstrip("@").lower()
    is_private = (chat_type or "").lower() == "private"
    if command == "/c":
        return is_private  # bare /c only in private
    return bool(username and command == f"/c@{username}")


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
) -> tuple[str | None, str | None, str | None]:
    """Returns (user_text, media_kind_override, media_context).
    media_kind_override may differ from geometry.target_media_kind for albums:
    e.g. an album with photos+videos resolves to 'video' as the routing kind.
    """
    if not _should_use_media_route(geometry):
        return None, None, None

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
        media_result = await handle_ptb_mention(
            msg.raw_update, context, bot_username
        )
    else:
        media_result = await handle_telethon_mention(
            msg.raw_update, bot_username
        )
    if isinstance(media_result, tuple):
        user_text = media_result[0] if len(media_result) >= 1 else None
        media_kind_hint = media_result[1] if len(media_result) >= 2 else None
        media_context = media_result[2] if len(media_result) >= 3 else None
    else:
        # Backward compatibility for older media routers/tests that returned
        # only the resolved instruction string.
        user_text = media_result
        media_kind_hint = None
        media_context = None

    logger.info(
        "flow.mention_route_done trace=%s user_text_len=%s media_kind=%s media_kind_hint=%s media_context_len=%s",
        trace,
        len(user_text or ""),
        geometry.target_media_kind or "",
        media_kind_hint or "",
        len(media_context or ""),
    )
    return user_text, media_kind_hint, media_context


async def build_user_task(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    media_instruction: str | None,
    media_type_override: str | None = None,
    media_context: str | None = None,
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
    # Album route resolves to a specific media kind ('video' for mixed albums,
    # 'image' for photo-only). Use the override when present; fall back to
    # geometry's single-target detection.
    effective_media_kind = (media_type_override or geometry.target_media_kind) or None
    task = UserTask(
        instruction=instruction,
        has_media_target=bool(effective_media_kind),
        media_type=effective_media_kind,
        media_context=media_context,
        needs_search_hint=_needs_search_hint(instruction),
        is_instruction_on_target=bool(target_message_id and instruction),
        target_message_id=target_message_id,
        target_message_text=target_message_text,
        turn_context_msgs=render_turn_context_messages(geometry),
        should_store_user_message=should_store_user_message,
    )
    logger.info(
        "flow.task_built trace=%s instruction_len=%s media_target=%s media_type=%s media_context_len=%s search_hint=%s target_text_len=%s",
        trace,
        len(task.instruction),
        task.has_media_target,
        task.media_type or "",
        len(task.media_context or ""),
        task.needs_search_hint,
        len(task.target_message_text or ""),
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
        if recent_rows:
            dialogue_context = tuple(
                {"role": row["role"], "content": row["content"]}
                for row in recent_rows
                if row.get("content")
            )
    except Exception:
        pass  # Planner works without context — just less accurately.

    decision = plan_message(
        PlannerInput(
            user_text=task.instruction,
            is_private=geometry.chat_type == "private",
            addressed_via_mention=geometry.addressed_via_mention,
            reply_to_bot=geometry.reply_to_bot,
            has_media_context=task.has_media_target,
            media_kind=task.media_type,
            dialogue_context=dialogue_context,
        )
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
    turn_context_msgs = list(task.turn_context_msgs)
    if task.media_context:
        # The current media target must outrank recalled [MEDIA] blocks.
        # Otherwise vision answers can accidentally describe an older image
        # selected by memory retrieval instead of the photo from this turn.
        turn_context_msgs.insert(
            0,
            {
                "role": "system",
                "content": f"[MEDIA_CURRENT]\n{task.media_context}",
            },
        )
    actual_route = plan.route
    actual_capability = plan.capability
    if plan.route == "search":
        answer = await run_search(
            chat_id,
            task.instruction,
            use_reasoning=plan.use_reasoning,
            turn_context_msgs=turn_context_msgs,
        )
    else:
        answer = await run_simple(
            chat_id,
            task.instruction,
            capability=plan.capability,
            use_reasoning=plan.use_reasoning,
            turn_context_msgs=turn_context_msgs,
        )
        if _looks_like_fake_search_block(answer):
            logger.warning(
                "flow.fake_search_block_reroute capability=%s text_len=%s",
                plan.capability,
                len(answer or ""),
            )
            answer = await run_search(
                chat_id,
                task.instruction,
                use_reasoning=plan.use_reasoning,
                turn_context_msgs=turn_context_msgs,
            )
            actual_route = "search"
            actual_capability = "search_web"
    text = (answer or "").strip()
    if actual_route == "search" and text and SEARCH_PERFORMED_MARKER not in text:
        text = f"{text}\n\n{SEARCH_PERFORMED_MARKER}"
    return ExecutionResult(
        text=text,
        route=actual_route,
        capability=actual_capability,
    )


async def send_response(
    msg: UnifiedMessage,
    text: str,
    reply_to: int | None = None,
) -> None:
    rendered = render_telegram_html(text)
    if msg.platform == "ptb":
        kwargs: dict[str, Any] = {
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to is not None:
            kwargs["reply_to_message_id"] = reply_to
        await msg.raw_update.effective_message.reply_text(rendered, **kwargs)
        return

    kwargs = {"parse_mode": "html"}
    if reply_to is not None:
        kwargs["reply_to"] = reply_to
    try:
        await msg.raw_update.reply(rendered, link_preview=False, **kwargs)
    except TypeError:
        await msg.raw_update.reply(rendered, **kwargs)


def _participant_label(participant: Any) -> str:
    if participant is None:
        return ""
    parts = []
    display_name = (getattr(participant, "display_name", None) or "").strip()
    username = (getattr(participant, "username", None) or "").strip()
    user_id = getattr(participant, "user_id", None)
    if display_name:
        parts.append(display_name)
    if username:
        parts.append(f"@{username}")
    if user_id is not None:
        parts.append(f"id={user_id}")
    return " ".join(parts).strip()


def _build_chat_turn_memory_event(geometry: MessageGeometry, task: UserTask) -> str:
    lines = ["[CHAT-TURN]"]
    if geometry.chat_type:
        lines.append(f"chat_type: {geometry.chat_type}")
    sender = _participant_label(geometry.sender)
    if sender:
        lines.append(f"sender: {sender}")
    sender_user_id = getattr(geometry.sender, "user_id", None)
    if sender_user_id is not None:
        lines.append(f"sender_user_id: {sender_user_id}")
    sender_username = (getattr(geometry.sender, "username", None) or "").strip()
    if sender_username:
        lines.append(f"sender_username: @{sender_username}")
    sender_display_name = (getattr(geometry.sender, "display_name", None) or "").strip()
    if sender_display_name:
        lines.append(f"sender_display_name: {sender_display_name}")
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
    reply_author = _participant_label(geometry.reply_target.author)
    if reply_author:
        lines.append(f"reply_target_author: {reply_author}")
    reply_author_user_id = getattr(geometry.reply_target.author, "user_id", None)
    if reply_author_user_id is not None:
        lines.append(f"reply_target_author_user_id: {reply_author_user_id}")
    reply_author_username = (
        getattr(geometry.reply_target.author, "username", None) or ""
    ).strip()
    if reply_author_username:
        lines.append(f"reply_target_author_username: @{reply_author_username}")
    if geometry.reply_target.media_kind:
        lines.append(f"reply_target_media_kind: {geometry.reply_target.media_kind}")
    if task.target_message_text:
        # When the user replied to the bot's OWN previous message, the target
        # text is already in recent memory as an assistant turn — duplicating
        # it into [CHAT-TURN] would later be lifted into [Speaker:] header on
        # the user message and act as a strong "continue this topic" signal,
        # even for unrelated follow-ups like a bare "привіт". Skip the text
        # in that case; the reply_to_bot flag itself carries the geometry.
        # For reply-to-other-user, keep the quoted text — it provides
        # geometry context the model wouldn't otherwise see.
        if not geometry.reply_to_bot:
            lines.append(f"reply_target_text: {task.target_message_text[:1200]}")
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
    await memory_manager.append_message(
        chat_id,
        "system",
        _build_chat_turn_memory_event(geometry, task),
    )
    if not task.should_store_user_message:
        await memory_manager.ensure_budget(chat_id)
        return
    await memory_manager.append_message(chat_id, "user", task.instruction)
    await memory_manager.ensure_budget(chat_id)


async def _append_assistant_reply(chat_id: int, text: str) -> None:
    await memory_manager.append_message(chat_id, "assistant", text)
    await memory_manager.ensure_budget(chat_id)


def _turn_failure_message(exc: BaseException) -> str:
    """User-facing message when a turn blew up — so they don't wait silently."""
    exc_name = type(exc).__name__.lower()
    detail = str(exc)[:180]
    lowered_detail = detail.lower()
    if "timeout" in exc_name or "timeout" in lowered_detail:
        return (
            "⚠️ Модель не відповіла вчасно (timeout після кількох спроб). "
            "Спробуй ще раз через хвилину або переформулюй запит."
        )
    if "connection" in exc_name:
        return (
            "⚠️ Не вдалось достукатись до провайдера. "
            "Імовірно, проблема з мережею — спробуй ще раз."
        )
    if "rate" in lowered_detail or "429" in detail:
        return (
            "⚠️ Провайдер зараз обмежує запити (rate limit). "
            "Почекай 30-60 секунд і спробуй ще."
        )
    return (
        "⚠️ Запит обісрався на нашому боці. "
        "Можеш спробувати ще раз — можливо, провайдер знов відкине."
    )


async def process_message(msg: UnifiedMessage) -> None:
    trace = _trace_id(msg)
    if not _claim_message_once(msg):
        logger.info("flow.duplicate_skip trace=%s", trace)
        return
    try:
        await _process_message_inner(msg, trace)
    except Exception as exc:
        logger.error(
            "flow.turn_failed trace=%s error_type=%s error=%s",
            trace,
            type(exc).__name__,
            str(exc)[:500],
            exc_info=True,
        )
        notice = _turn_failure_message(exc)
        try:
            await send_response(msg, notice)
        except Exception as notify_exc:
            logger.error(
                "flow.turn_failed_notify_error trace=%s error=%s",
                trace,
                notify_exc,
            )


async def _process_message_inner(msg: UnifiedMessage, trace: str) -> None:
    # Register every album item before geometry resolution, so any sibling
    # item can see captions/text from this one.
    observe_album_message(msg)

    geometry = await resolve_message_geometry(msg)
    msg.geometry = geometry
    session_state = _session_state(msg.chat_id, await get_settings(msg.chat_id) or {})

    # ── Album gate: only one item per media_group_id processes ────────
    album_claimed = False
    if msg.media_group_id:
        album_claimed = claim_album_processing(msg)
        if not album_claimed:
            logger.info(
                "flow.album_skip_duplicate trace=%s group_id=%s message_id=%s",
                trace, msg.media_group_id, msg.message_id,
            )
            return
        logger.info(
            "flow.album_claimed trace=%s group_id=%s settle=%.1f",
            trace, msg.media_group_id, ALBUM_PROCESSING_SETTLE_SECONDS,
        )
        await asyncio.sleep(ALBUM_PROCESSING_SETTLE_SECONDS)
        # After settle, check if any item carries text — promote album
        # addressed if so (the @mention may live on a sibling caption).
        items = _album_items_for(
            msg.platform, int(msg.chat_id), msg.media_group_id or "",
        )
        album_text = next(
            ((it.text or "").strip() for it in items if (it.text or "").strip()),
            "",
        )
        if not geometry.addressed and album_text:
            # Re-resolve geometry so caption-mention from sibling item counts.
            # Simplest: if text looks like it mentions us, mark addressed.
            bot_username = (msg.bot_username or "").strip().lower()
            if bot_username and f"@{bot_username}" in album_text.lower():
                geometry = _dc_replace(
                    geometry,
                    addressed=True,
                    addressed_via_mention=True,
                    clean_text=album_text.replace(f"@{msg.bot_username}", "").strip(),
                    target_media_kind=geometry.current_media_kind or geometry.target_media_kind,
                )
                msg.geometry = geometry

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

    if _is_clear_context_command(
        _raw_text(msg), msg.bot_username or "", chat_type=geometry.chat_type
    ):
        await memory_manager.clear_all(msg.chat_id)
        logger.info("flow.memory_cleared trace=%s chat_id=%s", trace, msg.chat_id)
        await send_response(
            msg,
            "Контекст цього чату повністю очищено. Починаємо з нуля.",
        )
        return

    access = await check_access(msg, geometry, session_state)
    if access.should_stop:
        if access.response_text:
            await send_response(msg, access.response_text)
        return

    # ── Voice commands /a /v ────────────────────────────────────────
    raw_text = _raw_text(msg)
    voice_cmd, voice_payload, _ = _parse_voice_command(raw_text, msg.bot_username or "")
    if voice_cmd is not None:
        # In group, bare /a or /v (no @bot tag) is ignored UNLESS the user
        # already addressed us via reply-to-bot. Multi-bot safety rule:
        # bare /a/v shouldn't trigger in a multi-bot chat where users talk
        # to other bots — but if the user explicitly replied to OUR message,
        # there's no conflict, the addressing is unambiguous.
        is_bare = "@" not in raw_text.split(maxsplit=1)[0]
        if (
            geometry.chat_type != "private"
            and is_bare
            and not geometry.reply_to_bot
        ):
            logger.info("flow.voice_cmd_ignored_bare_in_group trace=%s", trace)
            return

        text_to_speak = ""
        if voice_cmd == "speak_text":
            # /a <text> → speak text from command
            # /a as reply (empty payload) → speak text from reply target
            if voice_payload:
                text_to_speak = voice_payload
            elif geometry.reply_target and geometry.reply_target.text:
                text_to_speak = geometry.reply_target.text
        elif voice_cmd == "speak_last":
            # B-012 DROP: /v always speaks the last assistant text, regardless
            # of whether it's a reply. /a covers the "speak this specific
            # message" use-case; /v's only job is "speak your last reply".
            text_to_speak = await _find_last_assistant_reply_text(msg.chat_id)

        if not text_to_speak.strip():
            await send_response(msg, _voice_command_error_message(voice_cmd))
            logger.info("flow.voice_cmd_empty trace=%s cmd=%s", trace, voice_cmd)
            return

        try:
            await send_voice_response(msg, text_to_speak)
            logger.info(
                "flow.voice_cmd_done trace=%s cmd=%s len=%s",
                trace, voice_cmd, len(text_to_speak),
            )
        except Exception as exc:
            logger.exception("flow.voice_cmd_failed trace=%s cmd=%s", trace, voice_cmd)
            await send_response(msg, _voice_command_error_message(voice_cmd))
        return

    media_instruction, media_kind_override, media_context = await _resolve_media_instruction(msg, geometry)
    task = await build_user_task(
        msg,
        geometry,
        media_instruction,
        media_type_override=media_kind_override,
        media_context=media_context,
    )
    if task is None:
        return

    await _append_user_task(msg.chat_id, task, geometry)
    plan = await plan_execution(msg.chat_id, task, geometry, access.session_state)
    logger.info(
        "flow.planner_decision trace=%s route=%s capability=%s source=%s reasoning=%s text_len=%s",
        trace,
        plan.route,
        plan.capability,
        plan.planner_source,
        plan.use_reasoning,
        len(task.instruction or ""),
    )

    result = await execute_plan(msg.chat_id, task, plan)
    if not result.text:
        # Provider returned empty content (Gemini sometimes does). Don't
        # silently ignore — user tagged the bot and waits for response.
        logger.warning(
            "flow.empty_answer trace=%s capability=%s — surfacing error",
            trace, plan.capability,
        )
        await send_response(
            msg,
            "⚠️ Модель повернула порожню відповідь. "
            "Спробуй переформулювати або повторити запит.",
        )
        if album_claimed:
            finish_album_processing(msg, handled=False)
        return

    # Append debug markers so user can visually verify which path ran.
    answer_text = result.text
    if result.route == "search" and SEARCH_PERFORMED_MARKER not in answer_text:
        answer_text = f"{answer_text.rstrip()}\n\n{SEARCH_PERFORMED_MARKER}"
    if plan.use_reasoning:
        answer_text = f"{answer_text.rstrip()}\n\n{REASONING_MARKER}"

    logger.info("flow.reply_ready trace=%s answer_len=%s", trace, len(answer_text))
    if _should_reply_with_voice(geometry):
        try:
            await send_voice_response(msg, answer_text)
            logger.info("flow.voice_reply_sent trace=%s", trace)
        except Exception as exc:
            logger.exception("flow.voice_reply_failed trace=%s", trace)
            await send_response(msg, answer_text)
    else:
        await send_response(msg, answer_text)
        logger.info("flow.reply_sent trace=%s platform=%s", trace, msg.platform)
    await _append_assistant_reply(msg.chat_id, answer_text)
    if album_claimed:
        finish_album_processing(msg, handled=True)
    logger.info("flow.done trace=%s", trace)
