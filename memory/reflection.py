"""Reflection: synthesize core beliefs from repeated long-term memory patterns."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from agent.llm import chat_once
from core.prompts import REFLECTION_SYSTEM_PROMPT, REFLECTION_USER_TEMPLATE
from core.tokens import count_tokens_text
from db.memory_repository import (
    core_total_tokens,
    fetch_core_fact,
    fetch_long_all,
    upsert_core_fact,
)
from db.settings_repository import get_last_reflection, is_memory_persist_enabled, set_last_reflection

logger = logging.getLogger(__name__)

_REFLECTION_INTERVAL_DAYS = 3
_MIN_GROUP_SIZE = 3
_MIN_AVG_IMPORTANCE = 0.6  # importance in DB is 0.0-1.0 scale


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords (len > 3) from text."""
    words = re.findall(r"\w+", text.lower())
    return {w for w in words if len(w) > 3}


def _group_by_keywords(entries: List[Dict]) -> List[List[Dict]]:
    """Group entries that share significant keyword overlap."""
    if not entries:
        return []

    # Build keyword sets
    entry_kws = [(e, _extract_keywords(e.get("summary", ""))) for e in entries]
    used = set()
    groups = []

    for i, (entry_i, kw_i) in enumerate(entry_kws):
        if i in used or not kw_i:
            continue
        group = [entry_i]
        used.add(i)

        for j, (entry_j, kw_j) in enumerate(entry_kws):
            if j in used or not kw_j:
                continue
            overlap = len(kw_i & kw_j)
            union = len(kw_i | kw_j)
            if union > 0 and overlap / union >= 0.3:  # Jaccard >= 0.3
                group.append(entry_j)
                used.add(j)

        if len(group) >= _MIN_GROUP_SIZE:
            groups.append(group)

    return groups


async def reflect(chat_id: int):
    """Analyze long-term memories and synthesize core beliefs."""
    entries = await fetch_long_all(chat_id)
    if not entries:
        return

    groups = _group_by_keywords(entries)

    for group in groups:
        avg_imp = sum(float(e.get("importance", 0)) for e in group) / len(group)
        if avg_imp < _MIN_AVG_IMPORTANCE:
            continue

        memories_text = "\n---\n".join(e.get("summary", "") for e in group)

        try:
            prompt_user = REFLECTION_USER_TEMPLATE.format(memories_text=memories_text)
            resp = await asyncio.to_thread(
                chat_once,
                [
                    {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt_user},
                ],
                tools=None,
                use_reasoning=False,
                temperature=0.2,
                capability="memory_summary",
                max_tokens=200,
            )
            raw = (resp.choices[0].message.content or "").strip()
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if not json_match:
                continue
            data = json.loads(json_match.group())
            key = data.get("belief_key", "").strip()
            value = data.get("belief_value", "").strip()
            if not key or not value:
                continue

            tokens = count_tokens_text(f"{key}: {value}")
            from os import getenv
            core_budget = int(getenv("MEMORY_CORE_BUDGET", "1000"))
            current = await core_total_tokens(chat_id)
            existing = await fetch_core_fact(chat_id, key)
            existing_tokens = int(existing["tokens"] or 0) if existing else 0
            if current - existing_tokens + tokens > core_budget:
                continue  # No room even after replacing

            await upsert_core_fact(
                chat_id, key, value,
                source="inferred", confidence=200.0, tokens=tokens,
            )
            logger.info("reflection.belief_created chat=%s key=%s", chat_id, key)

        except Exception as exc:
            logger.warning("reflection.synthesize_failed chat=%s: %s", chat_id, exc)


async def maybe_reflect_all(chat_ids: List[int]):
    """Run reflection for chats that haven't been reflected in _REFLECTION_INTERVAL_DAYS."""
    now = datetime.now(timezone.utc)

    for chat_id in chat_ids:
        try:
            persist = await is_memory_persist_enabled(chat_id)
            if not persist:
                continue

            last = await get_last_reflection(chat_id)
            if last:
                if isinstance(last, datetime):
                    last_aware = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
                else:
                    continue
                if now - last_aware < timedelta(days=_REFLECTION_INTERVAL_DAYS):
                    continue

            await reflect(chat_id)
            await set_last_reflection(chat_id)
        except Exception as exc:
            logger.error(
                "reflection.error chat=%s: %s", chat_id, exc, exc_info=True
            )
