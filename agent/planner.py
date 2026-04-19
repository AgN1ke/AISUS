from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from agent.llm import chat_once, make_messages
from agent.search_task import is_explicit_search_request
from core.env import capability_reasoning_enabled, env_bool
from core.prompts import PLANNER_SYSTEM_PROMPT, SEARCH_GATE_SYSTEM_PROMPT
from core.reasoning import explicit_reasoning_requested

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


def _needs_reasoning(user_text: str) -> bool:
    return explicit_reasoning_requested(user_text)


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
    route = (value or "").strip().lower()
    if route in {"search", "image", "video", "voice", "document", "chat"}:
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
            route="chat",
            capability="chat_final",
            use_reasoning=_needs_reasoning(task.user_text),
            planner_source="heuristic",
            notes="voice_input_transcribed",
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
    if is_explicit_search_request(task.user_text):
        return PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=_needs_reasoning(task.user_text),
            planner_source="heuristic",
            notes="explicit_search_intent",
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
            if content.startswith("[CHAT-TURN]"):
                relevant.append(content[:400])
                continue
            if content.startswith("[THREAD-HISTORY]"):
                relevant.append(content[:600])
                continue
            if content.startswith("[PARTICIPANT-HISTORY]"):
                relevant.append(content[:400])
                continue
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
    capability = parsed.get("capability") or _capability_for_route(route)
    use_reasoning = bool(parsed.get("use_reasoning"))
    notes = str(parsed.get("notes") or "").strip()
    if capability != _capability_for_route(route):
        capability = _capability_for_route(route)

    return PlanDecision(
        route=route,
        capability=capability,
        use_reasoning=use_reasoning,
        planner_source="llm",
        notes=notes,
    )


def _validate_search(task: PlannerInput) -> bool:
    """Second-opinion gate: returns True if search is genuinely needed."""
    user_msg = (task.user_text or "").strip()[:600]
    dialogue_text = _format_dialogue_excerpt(task.dialogue_context, limit=3)
    if dialogue_text:
        content = f"[Контекст діалогу]\n{dialogue_text}\n\n[Питання]\n{user_msg}"
    else:
        content = user_msg
    messages = make_messages(SEARCH_GATE_SYSTEM_PROMPT, [], content)
    try:
        response = chat_once(
            messages,
            tools=None,
            use_reasoning=False,
            temperature=0,
            capability="planner_reasoning",
        )
        verdict = (response.choices[0].message.content or "").strip().upper()
        logger.info("planner.search_gate verdict=%s query=%s", verdict, user_msg[:120])
        return verdict.startswith("SEARCH")
    except Exception as exc:
        logger.warning("planner.search_gate_failed error=%s", exc)
        return True  # on failure, allow search through


def plan_message(task: PlannerInput) -> PlanDecision:
    fallback = _heuristic_plan(task)
    explicit_reasoning = _needs_reasoning(task.user_text)
    if _should_short_circuit(task):
        return fallback
    if not _planner_enabled():
        return fallback

    try:
        planned = _plan_with_model(task)
    except Exception as exc:
        logger.warning("planner.llm_failed error=%s", exc)
        return fallback

    decision = planned or fallback

    # Override: if user explicitly asked to search, force search route
    # regardless of what the LLM planner decided
    if (
        fallback.route == "search"
        and fallback.notes == "explicit_search_intent"
        and decision.route != "search"
    ):
        logger.info(
            "planner.explicit_search_override llm_route=%s", decision.route,
        )
        decision = fallback

    # Search gate: if planner chose search but it's not an explicit /search command,
    # validate with a focused second opinion
    if (
        decision.route == "search"
        and decision.planner_source != "heuristic"
        and not is_explicit_search_request(task.user_text)
    ):
        if not _validate_search(task):
            logger.info("planner.search_gate_blocked original_notes=%s", decision.notes)
            decision = PlanDecision(
                route="chat",
                capability="chat_final",
                use_reasoning=decision.use_reasoning,
                planner_source="gate_override",
            notes=f"gate_blocked:{decision.notes}",
        )

    if explicit_reasoning and capability_reasoning_enabled(decision.capability):
        decision = PlanDecision(
            route=decision.route,
            capability=decision.capability,
            use_reasoning=True,
            planner_source=decision.planner_source,
            notes=decision.notes,
        )

    if decision.use_reasoning and not capability_reasoning_enabled(decision.capability):
        decision = PlanDecision(
            route=decision.route,
            capability=decision.capability,
            use_reasoning=False,
            planner_source=decision.planner_source,
            notes=decision.notes,
        )

    return decision
