from __future__ import annotations

import logging
import re
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
from media.router import handle_ptb_mention, handle_telethon_mention
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
) -> tuple[str | None, bool]:
    if not _should_use_media_route(geometry):
        return None, False

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
        user_text = await handle_ptb_mention(msg.raw_update, context, bot_username)
    else:
        user_text = await handle_telethon_mention(msg.raw_update, bot_username)

    logger.info(
        "flow.mention_route_done trace=%s user_text_len=%s media_kind=%s",
        trace,
        len(user_text or ""),
        geometry.target_media_kind or "",
    )
    return user_text, True


async def build_user_task(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    media_instruction: str | None,
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
    task = UserTask(
        instruction=instruction,
        has_media_target=bool(geometry.target_media_kind),
        media_type=geometry.target_media_kind,
        media_context=None,
        needs_search_hint=_needs_search_hint(instruction),
        is_instruction_on_target=bool(target_message_id and instruction),
        target_message_id=target_message_id,
        target_message_text=target_message_text,
        turn_context_msgs=render_turn_context_messages(geometry),
        should_store_user_message=should_store_user_message,
    )
    logger.info(
        "flow.task_built trace=%s instruction_len=%s media_target=%s media_type=%s search_hint=%s",
        trace,
        len(task.instruction),
        task.has_media_target,
        task.media_type or "",
        task.needs_search_hint,
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


async def _append_user_task(chat_id: int, task: UserTask) -> None:
    if not task.should_store_user_message:
        return
    await memory_manager.append_message(chat_id, "user", task.instruction)
    await memory_manager.ensure_budget(chat_id)


async def _append_assistant_reply(chat_id: int, text: str) -> None:
    await memory_manager.append_message(chat_id, "assistant", text)
    await memory_manager.ensure_budget(chat_id)


async def process_message(msg: UnifiedMessage) -> None:
    trace = _trace_id(msg)
    geometry = await resolve_message_geometry(msg)
    msg.geometry = geometry
    session_state = _session_state(msg.chat_id, await get_settings(msg.chat_id) or {})

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

    access = await check_access(msg, geometry, session_state)
    if access.should_stop:
        if access.response_text:
            await send_response(msg, access.response_text)
        return

    media_instruction, _ = await _resolve_media_instruction(msg, geometry)
    task = await build_user_task(msg, geometry, media_instruction)
    if task is None:
        return

    await _append_user_task(msg.chat_id, task)
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
        logger.warning("flow.empty_answer trace=%s", trace)
        return

    logger.info("flow.reply_ready trace=%s answer_len=%s", trace, len(result.text))
    await send_response(msg, result.text)
    logger.info("flow.reply_sent trace=%s platform=%s", trace, msg.platform)
    await _append_assistant_reply(msg.chat_id, result.text)
    logger.info("flow.done trace=%s", trace)
