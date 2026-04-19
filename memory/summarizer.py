from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

from agent.llm import chat_once
from core.prompts import (
    FACT_EXTRACTION_SYSTEM_PROMPT,
    FACT_EXTRACTION_USER_TEMPLATE,
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


async def _run_summary_model(prompt_user: str):
    return await asyncio.to_thread(
        chat_once,
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
        resp = await _run_summary_model(prompt_user)
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


async def extract_profile_facts(
    block_text: str, core_context: str
) -> List[Dict]:
    """
    Extract stable user facts from a conversation block.
    Returns: [{"key": str, "value": str, "source": str, "confidence": float}]
    """
    prompt_user = FACT_EXTRACTION_USER_TEMPLATE.format(
        core_context=core_context or "(порожньо)",
        block=block_text[:4000],
    )
    try:
        resp = await asyncio.to_thread(
            chat_once,
            [
                {"role": "system", "content": FACT_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt_user},
            ],
            tools=None,
            use_reasoning=False,
            temperature=0.1,
            capability="memory_summary",
            max_tokens=400,
        )
        raw = resp.choices[0].message.content.strip()
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            data = json.loads(json_match.group())
        else:
            return []
        return data.get("profile_facts", [])
    except Exception as exc:
        logger.warning("summarizer.extract_profile_facts failed: %s", exc)
        return []


async def compress_entry(text: str, core_context: str) -> str:
    """Compress a single long-term memory entry to a shorter version."""
    prompt = (
        f"Стисни цей спогад максимально коротко, збережи лише суть:\n\n{text}\n\n"
        f"Контекст ядра: {core_context or '(немає)'}\n\n"
        "Поверни тільки стиснений текст, без пояснень."
    )
    try:
        resp = await asyncio.to_thread(
            chat_once,
            [{"role": "user", "content": prompt}],
            tools=None,
            use_reasoning=False,
            temperature=0.1,
            capability="memory_summary",
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("summarizer.compress_entry failed: %s", exc)
        # Fallback: truncate to ~40% of original
        return text[: max(20, len(text) * 2 // 5)]
