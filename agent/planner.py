from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from agent.llm import chat_once, make_messages
from agent.search_task import is_explicit_search_request
from core.env import env_bool
from core.prompts import PLANNER_SYSTEM_PROMPT, SEARCH_GATE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannerInput:
    user_text: str
    is_private: bool = False
    addressed_via_mention: bool = False
    reply_to_bot: bool = False
    has_media_context: bool = False
    media_kind: Optional[str] = None
    dialogue_context: tuple[dict, ...] = ()


@dataclass(frozen=True)
class PlanDecision:
    route: str
    capability: str
    use_reasoning: bool
    planner_source: str
    notes: str = ""


def _planner_enabled() -> bool:
    return env_bool("PLANNER_ENABLED", default=True)


def _search_enabled() -> bool:
    return env_bool("SEARCH_ENABLED", default=True)


def _needs_reasoning(user_text: str) -> bool:
    text = (user_text or "").strip().lower()
    return text.startswith("/think")


def _capability_for_route(route: str) -> str:
    mapping = {
        "chat": "chat_final",
        "search": "search_web",
        "image": "vision_image",
        "video": "video_understanding",
        "voice": "stt_voice",
        "document": "document_context",
    }
    return mapping.get(route, "chat_final")


def _normalize_route(value: str | None) -> str:
    """Allowed routes after planner decision.

    Session 109 revert: planner CAN now pick `search` directly. The
    secondary `_validate_search` gate then verifies search picks (filter,
    not promoter). This restores the original two-stage architecture:
    primary picks → secondary gate confirms or downgrades.
    """
    route = (value or "").strip().lower()
    if route in {"image", "video", "voice", "document", "chat", "search"}:
        return route
    return "chat"


def _extract_json_block(text: str) -> Optional[dict]:
    raw = (text or "").strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _heuristic_plan(task: PlannerInput) -> PlanDecision:
    """Fallback when the LLM router is disabled or fails.

    Pure media-routing — no keyword matching for search intent. Search
    routing is decided by the dedicated intent classifier, never by regex.
    """
    media_kind = (task.media_kind or "").strip().lower()
    if media_kind == "video":
        return PlanDecision(
            route="video",
            capability="video_understanding",
            use_reasoning=_needs_reasoning(task.user_text),
            planner_source="heuristic",
            notes="target_video",
        )
    if media_kind in {"voice", "audio"}:
        return PlanDecision(
            route="voice",
            capability="stt_voice",
            use_reasoning=_needs_reasoning(task.user_text),
            planner_source="heuristic",
            notes="target_voice",
        )
    if media_kind == "document":
        return PlanDecision(
            route="document",
            capability="document_context",
            use_reasoning=_needs_reasoning(task.user_text),
            planner_source="heuristic",
            notes="target_document",
        )
    if media_kind == "image":
        return PlanDecision(
            route="image",
            capability="vision_image",
            use_reasoning=_needs_reasoning(task.user_text),
            planner_source="heuristic",
            notes="target_image",
        )
    return PlanDecision(
        route="chat",
        capability="chat_final",
        use_reasoning=_needs_reasoning(task.user_text),
        planner_source="heuristic",
        notes="default_chat",
    )


def _should_short_circuit(task: PlannerInput) -> bool:
    return bool(task.media_kind)


def _format_dialogue_excerpt(dialogue_context: tuple[dict, ...], limit: int = 6) -> str:
    """Format recent dialogue messages into a readable excerpt for the planner."""
    relevant = []
    for msg in dialogue_context:
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            if content.startswith("[CHAT-GEOMETRY]"):
                continue
            if content.startswith("[LONG-MEMO]"):
                continue
            continue
        if role not in {"user", "assistant"}:
            continue
        relevant.append(f"{role}: {content[:400]}")
    return "\n".join(relevant[-limit:])


def _format_planner_user_message(task: PlannerInput) -> str:
    """Build a structured, human-readable user message for the planner model."""
    parts = []

    dialogue_text = _format_dialogue_excerpt(task.dialogue_context)
    if dialogue_text:
        parts.append(f"[Діалог]\n{dialogue_text}")

    parts.append(f"[Останнє повідомлення]\n{(task.user_text or '').strip()[:1200]}")

    meta_bits = []
    if task.is_private:
        meta_bits.append("приватний чат")
    else:
        meta_bits.append("груповий чат")
    if task.addressed_via_mention:
        meta_bits.append("звернулись через @mention")
    if task.reply_to_bot:
        meta_bits.append("reply на повідомлення бота")
    if task.has_media_context:
        meta_bits.append(f"є медіа: {task.media_kind or 'невідомий тип'}")
    if meta_bits:
        parts.append(f"[Мета] {', '.join(meta_bits)}")

    return "\n\n".join(parts)


def _plan_with_model(task: PlannerInput) -> Optional[PlanDecision]:
    user_message = _format_planner_user_message(task)
    messages = make_messages(
        PLANNER_SYSTEM_PROMPT,
        [],
        user_message,
    )
    response = chat_once(
        messages,
        tools=None,
        use_reasoning=False,
        temperature=0,
        capability="planner_reasoning",
    )
    content = response.choices[0].message.content or ""
    parsed = _extract_json_block(content)
    if not parsed:
        logger.warning("planner.parse_failed content=%s", content[:400])
        return None

    route = _normalize_route(parsed.get("route"))
    capability = _capability_for_route(route)
    use_reasoning = bool(parsed.get("use_reasoning"))
    notes = str(parsed.get("notes") or "").strip()

    return PlanDecision(
        route=route,
        capability=capability,
        use_reasoning=use_reasoning,
        planner_source="llm",
        notes=notes,
    )


def _recent_user_assistant_pairs(
    dialogue_context: tuple[dict, ...],
    *,
    limit: int = 4,
) -> list[dict]:
    """Tight slice of recent user/assistant turns for intent classification.

    Strips ALL system / service messages — no [SEARCH], [SEARCH-RESULT],
    [CHAT-TURN], [LONG-MEMO], [CHAT-GEOMETRY], etc. The classifier should
    reason about the user's CURRENT intent, not inherit "we were in search
    mode before" bias from past turns.
    """
    pairs: list[dict] = []
    for msg in dialogue_context:
        role = (msg.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        pairs.append({"role": role, "text": content[:300]})
    return pairs[-limit:]


def _validate_search(task: PlannerInput) -> bool:
    """Search-gate FILTER: runs only after the planner has already picked
    `search`. Returns True iff the gate confirms the user really wants
    fresh web data; False means downgrade to chat.

    Architecture (per devlog Session 098+, restored Session 109):
      1. Primary planner (heuristic / LLM) picks a route.
      2. If route == "search" → this gate validates with a focused payload
         (today_date + last_user_message + thin recent exchange — no system
         blocks, no memory dump).
      3. Fail-closed: classifier error → False → downgrade to chat.

    This is a FILTER, not a promoter. If the planner is uncertain it will
    pick chat (and the gate is never consulted). If the planner picks
    search, the gate has the final word — it cuts off false positives
    (game lore, engineering principles) without overriding an explicit
    chat decision.
    """
    user_msg = (task.user_text or "").strip()[:600]
    payload = {
        "today_date": _dt.datetime.utcnow().date().isoformat(),
        "last_user_message": user_msg,
        "recent_exchange": _recent_user_assistant_pairs(
            task.dialogue_context, limit=4
        ),
    }
    messages = [
        {"role": "system", "content": SEARCH_GATE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        response = chat_once(
            messages,
            tools=None,
            use_reasoning=False,
            temperature=0,
            capability="planner_reasoning",
        )
        verdict = (response.choices[0].message.content or "").strip().upper()
        logger.info(
            "planner.search_gate verdict=%s last=%s",
            verdict,
            user_msg[:120],
        )
        return verdict.startswith("SEARCH")
    except Exception as exc:
        logger.warning("planner.search_gate_failed error=%s", exc)
        # Fail closed: classifier unavailable → downgrade to chat.
        return False


def plan_message(task: PlannerInput) -> PlanDecision:
    fallback = _heuristic_plan(task)
    if _should_short_circuit(task):
        return fallback
    if not _planner_enabled():
        decision = fallback
    else:
        try:
            planned = _plan_with_model(task)
        except Exception as exc:
            logger.warning("planner.llm_failed error=%s", exc)
            planned = None
        decision = planned or fallback

    # Auto-downgrade BEFORE calling gate when user is in a reply-to-bot
    # conversation with NO explicit search keyword. The user is asking a
    # follow-up about what the bot just said — not requesting fresh web
    # data. Saves tokens and prevents false-positive searches on contextual
    # questions ("шо там пишуть?", "а коли це було?", "де саме?").
    #
    # IMPORTANT bypass (Session 115): if the user typed an EXPLICIT keyword
    # ("пошукай / загугли / погугли / гугли / знайди в інтернеті / шукай"),
    # honor it even in reply-to-bot mode. Session 114's blanket downgrade
    # killed legitimate "загугли X" replies (trace 257752/4/7/9: user wrote
    # "Гугли - сбу операція павутина" 4 times in a reply chain, all got
    # downgraded → bot kept answering from memory).
    if (
        _search_enabled()
        and decision.route == "search"
        and task.reply_to_bot
        and not is_explicit_search_request(task.user_text or "")
    ):
        logger.info(
            "planner.search_auto_downgrade reason=reply_to_bot last=%s",
            (task.user_text or "")[:120],
        )
        return PlanDecision(
            route="chat",
            capability="chat_final",
            use_reasoning=decision.use_reasoning,
            planner_source="search_auto_downgrade_reply_to_bot",
            notes="reply_to_bot_context_takes_precedence",
        )

    # Search-gate as FILTER (Session 109 revert):
    # If the primary planner picked `search`, the focused gate verifies the
    # decision. If gate downgrades — drop back to chat. This is the
    # original two-stage architecture: planner picks → gate filters.
    # Cost: one extra classifier call only when search was picked, not on
    # every chat turn.
    if (
        _search_enabled()
        and decision.route == "search"
        and (task.user_text or "").strip()
        and not _validate_search(task)
    ):
        decision = PlanDecision(
            route="chat",
            capability="chat_final",
            use_reasoning=decision.use_reasoning,
            planner_source="search_gate_downgrade",
            notes="search_intent_rejected_by_gate",
        )

    return decision
