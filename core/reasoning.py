from __future__ import annotations

_REASONING_TRIGGER_PREFIXES = ("/think",)
_REASONING_TRIGGER_PHRASES_UK = (
    "подумай",
    "роздумай",
    "поміркуй",
    "проаналізуй глибше",
    "детально розбери",
    "крок за кроком",
    "поясни детально",
    "запусти різонінг",
    "увімкни різонінг",
    "включи різонінг",
    "з reasoning",
    "з рiзонiнгом",
)
_REASONING_TRIGGER_PHRASES_EN = (
    "think",
    "reason",
    "think step by step",
    "analyze deeply",
    "think carefully",
    "step by step",
    "enable reasoning",
    "use reasoning",
)


def explicit_reasoning_requested(user_text: str) -> bool:
    text = (user_text or "").strip().lower()
    if not text:
        return False
    if any(text.startswith(prefix) for prefix in _REASONING_TRIGGER_PREFIXES):
        return True
    return any(
        phrase in text
        for phrase in (*_REASONING_TRIGGER_PHRASES_UK, *_REASONING_TRIGGER_PHRASES_EN)
    )
