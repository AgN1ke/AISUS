"""Importance agent: evaluates memory entries for cascading recompression."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from agent.llm import chat_once
from core.prompts import IMPORTANCE_EVAL_SYSTEM_PROMPT, IMPORTANCE_EVAL_USER_TEMPLATE
from core.tokens import count_tokens_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Identity / strong-signal keywords for heuristic fallback
# ---------------------------------------------------------------------------
_IDENTITY_WORDS = {"звати", "ім'я", "мене звати", "працюю", "живу", "я з"}
_STRONG_WORDS = {"не люблю", "завжди", "ніколи", "важливо", "критично", "ненавиджу"}


def heuristic_importance(text: str, age_days: int = 0, is_core: bool = False) -> int:
    """Keyword-based importance fallback (1–10) when LLM is unavailable."""
    score = 4
    lower = text.lower()

    if any(w in lower for w in _IDENTITY_WORDS):
        score += 3
    if any(w in lower for w in _STRONG_WORDS):
        score += 2
    if is_core:
        score += 3
    if age_days > 60 and score < 5:
        score -= 1
    if len(text) < 20:
        score -= 1

    return max(1, min(10, score))


async def evaluate_importance(
    entries: List[Dict[str, Any]],
    core_context: str,
) -> List[Dict[str, Any]]:
    """
    Evaluate importance of memory entries.

    Input entries: [{"id": int, "text": str, "age_days": int, "is_core_memory": bool}]
    Returns:       [{"id": int, "importance": int, "compressed_text": str|None, "reason": str}]
    """
    if not entries:
        return []

    entries_for_llm = [
        {"id": e["id"], "text": e["text"], "age_days": e.get("age_days", 0)}
        for e in entries
    ]

    try:
        prompt_user = IMPORTANCE_EVAL_USER_TEMPLATE.format(
            core_context=core_context or "(порожньо)",
            entries_json=json.dumps(entries_for_llm, ensure_ascii=False, indent=2),
        )
        resp = chat_once(
            [
                {"role": "system", "content": IMPORTANCE_EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": prompt_user},
            ],
            tools=None,
            use_reasoning=False,
            temperature=0.1,
            capability="memory_summary",
            max_tokens=600,
        )
        raw = resp.choices[0].message.content.strip()
        # Extract JSON from possible markdown wrapper
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError("No JSON found in response")

        evaluations = data.get("evaluations", [])
        result = []
        for ev in evaluations:
            result.append({
                "id": ev["id"],
                "importance": max(1, min(10, int(ev.get("importance", 5)))),
                "compressed_text": ev.get("compressed_text"),
                "reason": ev.get("reason", ""),
            })
        return result

    except Exception as exc:
        logger.warning("importance.evaluate_llm_failed: %s, using heuristic", exc)
        return _heuristic_fallback(entries)


def _heuristic_fallback(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for e in entries:
        imp = heuristic_importance(
            e["text"],
            age_days=e.get("age_days", 0),
            is_core=e.get("is_core_memory", False),
        )
        result.append({
            "id": e["id"],
            "importance": imp,
            "compressed_text": None,
            "reason": "heuristic",
        })
    return result
