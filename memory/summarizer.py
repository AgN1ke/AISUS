from __future__ import annotations

import os
import re
from typing import Dict, List

from agent.llm import chat_once
from core.prompts import (
    MEMORY_SUMMARY_SYSTEM_PROMPT,
    MEMORY_SUMMARY_USER_TEMPLATE,
)
from core.tokens import count_tokens_text

_SUM_MODEL = os.getenv("OPENAI_SUMMARIZER_MODEL", "gpt-4o-mini")


def _format_block(messages: List[Dict[str, str]]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "user")
        text = (m.get("content") or "").strip()
        if not text:
            continue
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _run_summary_model(prompt_user: str):
    return chat_once(
        [
            {"role": "system", "content": MEMORY_SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt_user},
        ],
        tools=None,
        use_reasoning=False,
        model=None,
        temperature=0.2,
        capability="memory_summary",
        max_tokens=400,
    )


async def summarize_block(messages: List[Dict[str, str]]) -> dict:
    """
    -> { 'summary': str, 'importance': float, 'tokens': int }
    """
    block = _format_block(messages)
    prompt_user = MEMORY_SUMMARY_USER_TEMPLATE.format(block=block)
    try:
        resp = _run_summary_model(prompt_user)
    except RuntimeError:
        resp = None

    if resp is None:
        summary = block[:200]
        return {
            "summary": summary,
            "importance": 0.5,
            "tokens": count_tokens_text(summary, _SUM_MODEL),
        }

    text = resp.choices[0].message.content.strip()

    sum_match = re.search(
        r"(?:ПІДСУМОК|SUMMARY):\s*(.+?)(?:\n+\w+:|$)", text, flags=re.S
    )
    imp_match = re.search(r"(?:ВАЖЛИВІСТЬ|IMPORTANCE):\s*([0-1](?:\.\d+)?)", text)
    summary = (sum_match.group(1).strip() if sum_match else text).strip()
    try:
        importance = float(imp_match.group(1)) if imp_match else 0.5
    except Exception:
        importance = 0.5

    return {
        "summary": summary,
        "importance": max(0.0, min(1.0, importance)),
        "tokens": count_tokens_text(summary, _SUM_MODEL),
    }
