from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable


_CREATE_PATTERNS = (
    r"\bзроби(?:мо|те|ш)?(?:\s+нам|\s+мені)?(?:\s+з\s+цього|\s+на\s+цю\s+тему|\s+по\s+цій\s+темі)?\s+подкаст\b",
    r"\bзбери(?:\s+нам|\s+мені)?(?:\s+з\s+цього|\s+на\s+цю\s+тему|\s+по\s+цій\s+темі)?\s+подкаст\b",
    r"\bзапиши(?:\s+нам|\s+мені)?(?:\s+з\s+цього|\s+на\s+цю\s+тему|\s+по\s+цій\s+темі)?\s+подкаст\b",
    r"\bзгенеруй(?:\s+нам|\s+мені)?(?:\s+з\s+цього|\s+на\s+цю\s+тему|\s+по\s+цій\s+темі)?\s+подкаст\b",
    r"\bпідготуй(?:\s+нам|\s+мені)?(?:\s+з\s+цього|\s+на\s+цю\s+тему|\s+по\s+цій\s+темі)?\s+подкаст\b",
)
_QUESTION_GUARDS = (
    r"\bяк\s+зробити\s+подкаст\b",
    r"\bщо\s+таке\s+подкаст\b",
    r"\bяк\s+створити\s+подкаст\b",
    r"\bможна\s+зробити\s+подкаст\b",
)
_AFFIRMATIVE_PREFIXES = (
    "так",
    "так,",
    "так ",
    "ага",
    "давай",
    "погнали",
    "підтверджую",
    "роби",
)
_NEGATIVE_PREFIXES = (
    "ні",
    "ні,",
    "не треба",
    "скасувати",
    "відміна",
)


@dataclass(frozen=True)
class PodcastPendingRequest:
    topic_label: str
    style_instruction: str
    request_text: str
    source_scope: str
    source_message_id: int | None
    anchor_excerpt: str

    def to_dict(self) -> dict[str, str | int | None]:
        return asdict(self)


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def is_explicit_podcast_request(text: str) -> bool:
    lowered = _normalize_space(text).lower()
    if not lowered or "подкаст" not in lowered:
        return False
    if any(re.search(pattern, lowered) for pattern in _QUESTION_GUARDS):
        return False
    return any(re.search(pattern, lowered) for pattern in _CREATE_PATTERNS)


def extract_podcast_style_instruction(text: str) -> str:
    normalized = _normalize_space(text)
    lowered = normalized.lower()
    for pattern in _CREATE_PATTERNS:
        match = re.search(pattern, lowered)
        if not match:
            continue
        tail = normalized[match.end():].strip(" .,:;—-")
        return tail
    return ""


def _clean_topic_candidate(text: str) -> str:
    cleaned = _normalize_space(text).strip(" .,:;—-")
    if not cleaned:
        return ""
    if len(cleaned) > 160:
        cleaned = cleaned[:157].rstrip(" .,:;—-") + "..."
    return cleaned


def _content_from_recent_row(row: dict) -> str:
    content = _normalize_space(str(row.get("content") or ""))
    if not content or content.startswith("["):
        return ""
    if "подкаст" in content.lower():
        return ""
    return content


def guess_podcast_topic_label(
    task,
    recent_rows: Iterable[dict] | None = None,
) -> tuple[str, str]:
    target_text = _clean_topic_candidate(getattr(task, "target_message_text", ""))
    if target_text:
        return target_text, "reply_target"

    for row in reversed(list(recent_rows or [])):
        content = _content_from_recent_row(row)
        if content and content != _normalize_space(getattr(task, "instruction", "")):
            return _clean_topic_candidate(content), "recent_context"

    instruction = _normalize_space(getattr(task, "instruction", ""))
    style = extract_podcast_style_instruction(instruction)
    fallback = instruction
    if style and fallback.endswith(style):
        fallback = fallback[: -len(style)].strip(" .,:;—-")
    fallback = re.sub(r"(?i)\bподкаст\b", "", fallback)
    fallback = re.sub(
        r"(?i)\b(зроби|збери|запиши|згенеруй|підготуй|нам|мені|з цього|на цю тему|по цій темі)\b",
        "",
        fallback,
    )
    fallback = _clean_topic_candidate(fallback)
    if fallback:
        return fallback, "request_text"
    return "остання релевантна тема цієї розмови", "generic_recent_context"


def build_podcast_pending_request(task, recent_rows: Iterable[dict] | None = None) -> PodcastPendingRequest:
    topic_label, scope = guess_podcast_topic_label(task, recent_rows)
    style_instruction = extract_podcast_style_instruction(getattr(task, "instruction", ""))
    anchor_excerpt = _clean_topic_candidate(getattr(task, "target_message_text", "")) or topic_label
    return PodcastPendingRequest(
        topic_label=topic_label,
        style_instruction=style_instruction,
        request_text=_normalize_space(getattr(task, "instruction", "")),
        source_scope=scope,
        source_message_id=getattr(task, "target_message_id", None),
        anchor_excerpt=anchor_excerpt,
    )


def render_podcast_confirmation(pending: PodcastPendingRequest) -> str:
    base = (
        f"Ти хочеш зробити подкаст на тему: <b>{pending.topic_label}</b>?"
        "\n\nНапиши <code>так</code>, якщо це вона. "
        "Якщо хочеш інший акцент або формат, допиши його одним повідомленням."
    )
    if pending.style_instruction:
        base += (
            "\n\nЯ вже бачу додаткове побажання до формату: "
            f"<i>{pending.style_instruction}</i>."
        )
    return base


def parse_podcast_confirmation(text: str) -> tuple[str, str]:
    normalized = _normalize_space(text)
    lowered = normalized.lower()
    if any(lowered.startswith(prefix) for prefix in _NEGATIVE_PREFIXES):
        return "cancel", ""
    if any(lowered.startswith(prefix) for prefix in _AFFIRMATIVE_PREFIXES):
        extra = normalized
        if extra.lower().startswith("так"):
            extra = extra[3:].lstrip(" ,.:;—-")
        elif extra.lower().startswith("роби"):
            extra = extra[4:].lstrip(" ,.:;—-")
        elif extra.lower().startswith("давай"):
            extra = extra[5:].lstrip(" ,.:;—-")
        elif extra.lower().startswith("підтверджую"):
            extra = extra[len("підтверджую"):].lstrip(" ,.:;—-")
        elif extra.lower().startswith("погнали"):
            extra = extra[len("погнали"):].lstrip(" ,.:;—-")
        elif extra.lower().startswith("ага"):
            extra = extra[3:].lstrip(" ,.:;—-")
        return "confirm", extra
    return "none", ""
