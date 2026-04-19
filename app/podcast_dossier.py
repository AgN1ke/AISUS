from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from db.memory_repository import fetch_core_all, fetch_long_all, fetch_recent


_STOPWORDS = {
    "а", "або", "але", "бо", "в", "від", "вже", "він", "вона", "вони", "ви", "де",
    "для", "до", "з", "за", "зі", "і", "й", "із", "їх", "її", "його", "коли", "на",
    "нам", "не", "ні", "ну", "по", "про", "це", "ця", "цей", "цю", "ти", "та", "те",
    "то", "той", "у", "як", "я", "ми", "тобто", "саме", "просто", "потім", "зроби",
    "подкаст", "подкасту", "подкасти", "цього", "теми", "тему", "цієї", "оце",
}


@dataclass(frozen=True)
class PodcastDossier:
    topic_label: str
    style_instruction: str
    source_scope: str
    source_message_id: int | None
    anchor_excerpt: str
    keyword_summary: list[str]
    user_interest_signals: list[str]
    recent_turns: list[str]
    core_facts: list[str]
    long_memory_notes: list[str]
    assembled_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9][A-Za-zА-Яа-яІіЇїЄєҐґ0-9-]{1,}", text or "")
    result: list[str] = []
    for word in words:
        lowered = word.lower()
        if lowered in _STOPWORDS:
            continue
        result.append(lowered)
    return result


def _parse_structured_system_fields(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in (content or "").splitlines()[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


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


def _recent_turn_bundles(recent_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in recent_rows:
        role = (row.get("role") or "").strip().lower()
        content = (row.get("content") or "").strip()
        if role == "system" and content.startswith("[CHAT-TURN]"):
            if current is not None:
                bundles.append(current)
            current = {
                "fields": _parse_structured_system_fields(content),
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


def _bundle_combined_text(bundle: dict[str, Any]) -> str:
    fields = bundle.get("fields") or {}
    parts = [
        fields.get("reply_target_text") or "",
        fields.get("current_user_text") or "",
        fields.get("resolved_instruction") or "",
        " ".join(bundle.get("user_messages") or []),
        " ".join(bundle.get("assistant_replies") or []),
    ]
    return _normalize_space(" ".join(part for part in parts if part))


def _keyword_overlap_count(text: str, keywords: set[str]) -> int:
    if not text or not keywords:
        return 0
    return len(set(_tokenize(text)) & keywords)


def _bundle_score(
    bundle: dict[str, Any],
    *,
    source_message_id: int | None,
    anchor_excerpt: str,
    keywords: set[str],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    fields = bundle.get("fields") or {}
    ids = _message_id_set_from_fields(fields)
    if source_message_id is not None and source_message_id in ids:
        score += 100
        reasons.append("message_id_anchor")
    combined = _bundle_combined_text(bundle)
    if anchor_excerpt and anchor_excerpt.lower() in combined.lower():
        score += 40
        reasons.append("anchor_excerpt")
    overlap = _keyword_overlap_count(combined, keywords)
    if overlap:
        score += overlap * 8
        reasons.append(f"keyword_overlap:{overlap}")
    if (fields.get("resolved_instruction") or "").strip():
        score += 2
    return score, reasons


def _select_relevant_bundles(
    bundles: list[dict[str, Any]],
    *,
    source_message_id: int | None,
    anchor_excerpt: str,
    keywords: set[str],
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, int, list[str], dict[str, Any]]] = []
    for idx, bundle in enumerate(bundles):
        score, reasons = _bundle_score(
            bundle,
            source_message_id=source_message_id,
            anchor_excerpt=anchor_excerpt,
            keywords=keywords,
        )
        if score <= 0:
            continue
        ranked.append((score, idx, reasons, bundle))
    if not ranked:
        return bundles[-4:]

    selected_indexes: set[int] = set()
    for score, idx, _reasons, _bundle in sorted(ranked, key=lambda item: (item[0], item[1])):
        if score >= 16 or idx >= max(0, len(bundles) - 4):
            selected_indexes.add(idx)
            if idx > 0:
                selected_indexes.add(idx - 1)
            if idx + 1 < len(bundles):
                selected_indexes.add(idx + 1)
    if not selected_indexes:
        selected_indexes = {idx for _score, idx, _reasons, _bundle in ranked[-4:]}
    return [bundles[idx] for idx in sorted(selected_indexes)][-8:]


def _bundle_turn_text(bundle: dict[str, Any]) -> str:
    fields = bundle.get("fields") or {}
    when = (
        fields.get("current_message_time_local")
        or fields.get("current_message_time_utc")
        or "unknown_time"
    )
    sender = (fields.get("sender") or "").strip() or "unknown_sender"
    parts = [f"{when} | sender: {sender}"]
    target = (fields.get("reply_target_text") or "").strip()
    user_text = (
        (fields.get("resolved_instruction") or "").strip()
        or (fields.get("current_user_text") or "").strip()
    )
    if target:
        parts.append(f"target: {target}")
    if user_text:
        parts.append(f"user: {user_text}")
    assistant = (bundle.get("assistant_replies") or [])
    if assistant:
        parts.append(f"assistant: {assistant[-1]}")
    return "\n".join(parts)


def _extract_interest_signals(
    bundles: Iterable[dict[str, Any]],
    *,
    keywords: set[str],
) -> list[str]:
    signals: list[str] = []
    seen: set[str] = set()
    for bundle in bundles:
        fields = bundle.get("fields") or {}
        candidates = [
            (fields.get("resolved_instruction") or "").strip(),
            (fields.get("current_user_text") or "").strip(),
            *((bundle.get("user_messages") or [])),
        ]
        for item in candidates:
            text = _normalize_space(item)
            if not text:
                continue
            if "подкаст" in text.lower():
                continue
            if _keyword_overlap_count(text, keywords) <= 0:
                continue
            if text in seen:
                continue
            seen.add(text)
            signals.append(text)
            if len(signals) >= 6:
                return signals
    return signals


def _pick_core_facts(core_rows: Iterable[dict[str, Any]], keywords: set[str]) -> list[str]:
    selected: list[str] = []
    for row in core_rows:
        fact = _normalize_space(f"{row.get('fact_key')}: {row.get('fact_value')}")
        if not fact:
            continue
        if keywords and _keyword_overlap_count(fact, keywords) <= 0:
            continue
        selected.append(fact)
        if len(selected) >= 8:
            break
    return selected


def _pick_long_memory(long_rows: Iterable[dict[str, Any]], keywords: set[str]) -> list[str]:
    selected: list[str] = []
    for row in long_rows:
        summary = _normalize_space(str(row.get("summary") or ""))
        if not summary:
            continue
        if keywords and _keyword_overlap_count(summary, keywords) <= 0:
            continue
        selected.append(summary)
        if len(selected) >= 6:
            break
    return selected


def _render_podcast_dossier(
    *,
    topic_label: str,
    style_instruction: str,
    source_scope: str,
    source_message_id: int | None,
    anchor_excerpt: str,
    keyword_summary: list[str],
    interest_signals: list[str],
    recent_turns: list[str],
    core_facts: list[str],
    long_memory_notes: list[str],
) -> str:
    lines = ["[PODCAST-DOSSIER]"]
    lines.append(f"topic: {topic_label}")
    lines.append(f"source_scope: {source_scope}")
    if source_message_id is not None:
        lines.append(f"source_message_id: {source_message_id}")
    if anchor_excerpt:
        lines.append(f"anchor_excerpt: {anchor_excerpt}")
    if style_instruction:
        lines.append(f"style_instruction: {style_instruction}")
    if keyword_summary:
        lines.append("topic_keywords: " + ", ".join(keyword_summary))
    if interest_signals:
        lines.append("user_interest_signals:")
        for item in interest_signals:
            lines.append(f"- {item}")
    if recent_turns:
        lines.append("relevant_conversation_turns:")
        for idx, turn in enumerate(recent_turns, start=1):
            lines.append(f"### turn_{idx}")
            lines.extend(turn.splitlines())
    if core_facts:
        lines.append("relevant_core_facts:")
        for item in core_facts:
            lines.append(f"- {item}")
    if long_memory_notes:
        lines.append("relevant_long_memory:")
        for item in long_memory_notes:
            lines.append(f"- {item}")
    return "\n".join(lines)


async def build_podcast_dossier(
    chat_id: int,
    pending: dict[str, Any],
    *,
    recent_rows: list[dict[str, Any]] | None = None,
    long_rows: list[dict[str, Any]] | None = None,
    core_rows: list[dict[str, Any]] | None = None,
) -> PodcastDossier:
    if recent_rows is None:
        recent_rows = await fetch_recent(chat_id, limit=140)
    if long_rows is None:
        long_rows = await fetch_long_all(chat_id)
    if core_rows is None:
        core_rows = await fetch_core_all(chat_id)

    topic_label = _normalize_space(str(pending.get("topic_label") or "")) or "невизначена тема"
    style_instruction = _normalize_space(str(pending.get("style_instruction") or ""))
    source_scope = _normalize_space(str(pending.get("source_scope") or "")) or "recent_context"
    anchor_excerpt = _normalize_space(str(pending.get("anchor_excerpt") or ""))
    source_message_id = pending.get("source_message_id")
    try:
        source_message_id = int(source_message_id) if source_message_id is not None else None
    except Exception:
        source_message_id = None

    keyword_summary = list(dict.fromkeys(_tokenize(" ".join(
        part for part in [topic_label, anchor_excerpt, pending.get("request_text") or ""] if part
    ))))[:12]
    keywords = set(keyword_summary)

    bundles = _recent_turn_bundles(recent_rows or [])
    relevant_bundles = _select_relevant_bundles(
        bundles,
        source_message_id=source_message_id,
        anchor_excerpt=anchor_excerpt,
        keywords=keywords,
    )
    recent_turns = [_bundle_turn_text(bundle) for bundle in relevant_bundles if _bundle_turn_text(bundle)]
    interest_signals = _extract_interest_signals(relevant_bundles, keywords=keywords)
    core_facts = _pick_core_facts(core_rows or [], keywords)
    long_memory_notes = _pick_long_memory(long_rows or [], keywords)

    assembled_text = _render_podcast_dossier(
        topic_label=topic_label,
        style_instruction=style_instruction,
        source_scope=source_scope,
        source_message_id=source_message_id,
        anchor_excerpt=anchor_excerpt,
        keyword_summary=keyword_summary,
        interest_signals=interest_signals,
        recent_turns=recent_turns,
        core_facts=core_facts,
        long_memory_notes=long_memory_notes,
    )

    return PodcastDossier(
        topic_label=topic_label,
        style_instruction=style_instruction,
        source_scope=source_scope,
        source_message_id=source_message_id,
        anchor_excerpt=anchor_excerpt,
        keyword_summary=keyword_summary,
        user_interest_signals=interest_signals,
        recent_turns=recent_turns,
        core_facts=core_facts,
        long_memory_notes=long_memory_notes,
        assembled_text=assembled_text,
    )
