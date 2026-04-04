from __future__ import annotations

import os
from typing import Dict, List, Tuple

from core.tokens import budget_trim_messages, count_tokens_messages, count_tokens_text
from db.memory_repository import (
    bump_long_usage,
    delete_recent_upto_pos,
    fetch_long_all,
    fetch_recent,
    insert_long_summary,
    insert_recent,
    recent_total_tokens,
)
from db.repositories import upsert_chat

from .summarizer import summarize_block


def _recent_budget() -> int:
    return int(os.getenv("MEMORY_RECENT_BUDGET", "10000"))


def _long_budget() -> int:
    return int(os.getenv("MEMORY_LONG_BUDGET", "30000"))


def _compress_portion() -> float:
    return float(os.getenv("MEMORY_COMPRESS_PORTION", "0.35"))


def _dialog_model() -> str:
    return os.getenv("OPENAI_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-4o-mini"


def _normalize_memory_role(role: str | None) -> str:
    value = (role or "").strip().lower()
    if value in {"user", "assistant", "system"}:
        return value
    # Historical media context was stored as `tool`, but plain chat completions
    # cannot accept tool messages without preceding tool_calls.
    if value == "tool":
        return "system"
    return "system"


class MemoryManager:
    async def _ensure_chat(self, chat_id: int):
        await upsert_chat(chat_id, title=None, lang=None)

    async def append_message(self, chat_id: int, role: str, content: str):
        await self._ensure_chat(chat_id)
        role = _normalize_memory_role(role)
        tokens = count_tokens_text(content, _dialog_model())
        await insert_recent(chat_id, role, content, tokens)

    async def ensure_budget(self, chat_id: int):
        await self._ensure_chat(chat_id)
        recent_budget = _recent_budget()
        total = await recent_total_tokens(chat_id)
        if total <= recent_budget:
            return

        target_free = int(recent_budget * _compress_portion())
        rows = await fetch_recent(chat_id)
        acc: List[Dict] = []
        acc_tokens = 0
        upto_pos = None

        for row in rows:
            acc.append(
                {
                    "role": _normalize_memory_role(row["role"]),
                    "content": row["content"],
                }
            )
            acc_tokens += int(row["tokens"])
            upto_pos = row["pos"]
            if acc_tokens >= target_free:
                break

        if not acc or upto_pos is None:
            return

        summary_rec = await summarize_block(acc)
        await insert_long_summary(
            chat_id,
            summary_rec["summary"],
            summary_rec["importance"],
            summary_rec["tokens"],
        )
        await delete_recent_upto_pos(chat_id, upto_pos)

    def _score(self, text: str, query: str) -> float:
        if not text or not query:
            return 0.0
        import re

        terms = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        if not terms:
            return 0.0
        lower_text = text.lower()
        score = 0.0
        for term in terms:
            score += lower_text.count(term)
        return score / (len(text) / 1000 + 1)

    async def _select_long_relevant(
        self, chat_id: int, user_query: str
    ) -> Tuple[List[Dict[str, str]], List[int]]:
        await self._ensure_chat(chat_id)
        longs = await fetch_long_all(chat_id)
        if not longs:
            return [], []

        scored = []
        for row in longs:
            summary = row["summary"] or ""
            relevance = self._score(summary, user_query)
            final = relevance * 0.7 + float(row["importance"] or 0.5) * 0.3
            scored.append((final, row))

        scored.sort(key=lambda item: item[0], reverse=True)

        selected: List[Dict[str, str]] = []
        selected_ids: List[int] = []
        budget_left = _long_budget()
        for _, row in scored:
            text = row["summary"] or ""
            tokens = int(row["tokens"] or 0)
            if tokens == 0:
                tokens = count_tokens_text(text)
            if tokens > budget_left:
                continue
            selected.append({"role": "system", "content": f"[LONG-MEMO] {text}"})
            selected_ids.append(int(row["id"]))
            budget_left -= tokens
            if budget_left <= 0:
                break
        return selected, selected_ids

    async def select_context(
        self, chat_id: int, user_query: str, system_prompt: str | None = None
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt.strip()})

        long_msgs, long_ids = await self._select_long_relevant(chat_id, user_query)
        messages.extend(long_msgs)

        recent_rows = await fetch_recent(chat_id)
        recent_msgs = [
            {
                "role": _normalize_memory_role(row["role"]),
                "content": row["content"],
            }
            for row in recent_rows
        ]
        recent_budget = _recent_budget()
        if count_tokens_messages(recent_msgs) > recent_budget:
            recent_msgs = budget_trim_messages(recent_msgs, recent_budget)
        messages.extend(recent_msgs)

        await bump_long_usage(long_ids)
        return messages
