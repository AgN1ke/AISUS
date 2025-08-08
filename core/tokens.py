from __future__ import annotations
import math
from typing import Iterable, Dict, Any

try:
    import tiktoken
except Exception:
    tiktoken = None

_DEFAULT_MODEL = "gpt-4o-mini"

_ENCODER_CACHE: dict[str, Any] = {}

def _get_encoder(model: str | None):
    model = model or _DEFAULT_MODEL
    if tiktoken is None:
        return None
    if model in _ENCODER_CACHE:
        return _ENCODER_CACHE[model]
    try:
        enc = tiktoken.encoding_for_model(model)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    _ENCODER_CACHE[model] = enc
    return enc

def count_tokens_text(text: str, model: str | None = None) -> int:
    if not text:
        return 0
    enc = _get_encoder(model)
    if enc is None:
        # груба оцінка: ~4 символи на токен
        return math.ceil(len(text) / 4)
    return len(enc.encode(text))

def count_tokens_messages(messages: Iterable[Dict[str, str]], model: str | None = None) -> int:
    total = 0
    for m in messages:
        total += count_tokens_text(m.get("content") or "", model)
        # невеликий запас на роль/системний формат
        total += 4
    return total

def budget_trim_messages(messages: list[Dict[str, str]], budget: int, model: str | None = None) -> list[Dict[str, str]]:
    """Обрізає з початку (найстаріші) поки не вліземо в бюджет."""
    acc: list[Dict[str, str]] = []
    for m in messages:
        acc.append(m)
        if count_tokens_messages(acc, model) > budget:
            # видаляємо з початку
            while count_tokens_messages(acc, model) > budget and acc:
                acc.pop(0)
            break
    # додаткова перевірка (на випадок дуже довгого одного повідомлення)
    while acc and count_tokens_messages(acc, model) > budget:
        acc.pop(0)
    return acc
