from __future__ import annotations
import os, re
from typing import List, Dict
from openai import OpenAI
from core.tokens import count_tokens_text
from .prompts import SUMMARY_SYSTEM, SUMMARY_USER_TEMPLATE

_SUM_MODEL = os.getenv("OPENAI_SUMMARIZER_MODEL", "gpt-4o-mini")
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or os.getenv("OPENAI_API_KEY_V1")

_client = OpenAI(api_key=_OPENAI_API_KEY) if _OPENAI_API_KEY else None

def _format_block(messages: List[Dict[str, str]]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "user")
        text = (m.get("content") or "").strip()
        if not text:
            continue
        lines.append(f"{role}: {text}")
    return "\n".join(lines)

async def summarize_block(messages: List[Dict[str,str]]) -> dict:
    """
    -> { 'summary': str, 'importance': float, 'tokens': int }
    """
    block = _format_block(messages)
    if _client is None:
        # Fallback: simple truncation summary when API key missing
        summary = block[:200]
        return {
            "summary": summary,
            "importance": 0.5,
            "tokens": count_tokens_text(summary, _SUM_MODEL),
        }
    prompt_user = SUMMARY_USER_TEMPLATE.format(block=block)
    resp = _client.chat.completions.create(
        model=_SUM_MODEL,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": prompt_user},
        ],
        temperature=0.2,
        max_tokens=400,
    )
    text = resp.choices[0].message.content.strip()

    # парсинг трьох секцій
    sum_match = re.search(r"ПІДСУМОК:\s*(.+?)(?:\n+\w+:|$)", text, flags=re.S)
    imp_match = re.search(r"ВАЖЛИВІСТЬ:\s*([0-1](?:\.\d+)?)", text)
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
