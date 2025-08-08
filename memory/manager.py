from __future__ import annotations
import os
from typing import List, Dict, Tuple
from datetime import datetime

from core.tokens import count_tokens_text, count_tokens_messages, budget_trim_messages
from db.memory_repository import (
    insert_recent, fetch_recent, recent_total_tokens,
    delete_recent_upto_pos, insert_long_summary, fetch_long_all, bump_long_usage
)
from .summarizer import summarize_block

RECENT_BUDGET = int(os.getenv("MEMORY_RECENT_BUDGET", "10000"))
LONG_BUDGET   = int(os.getenv("MEMORY_LONG_BUDGET", "30000"))
COMPRESS_PORTION = float(os.getenv("MEMORY_COMPRESS_PORTION", "0.35"))
DIALOG_MODEL = os.getenv("OPENAI_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-4o-mini"

class MemoryManager:
    """
    Зберігає недавні повідомлення повністю (до RECENT_BUDЖЕТ),
    старі шматки стискає у memory_long (до LONG_BUDЖЕТ).
    Відбір релевантних long-саммарі — простий скоринг за ключовими словами.
    """

    async def append_message(self, chat_id: int, role: str, content: str):
        tokens = count_tokens_text(content, DIALOG_MODEL)
        await insert_recent(chat_id, role, content, tokens)

    async def ensure_budget(self, chat_id: int):
        total = await recent_total_tokens(chat_id)
        if total <= RECENT_BUDGET:
            return

        # скільки приблизно стиснути (порція)
        target_free = int(RECENT_BUDGET * COMPRESS_PORTION)
        rows = await fetch_recent(chat_id)  # від найстаріших
        acc: List[Dict] = []
        acc_tokens = 0
        upto_pos = None

        for r in rows:
            acc.append({"role": r["role"], "content": r["content"]})
            acc_tokens += int(r["tokens"])
            upto_pos = r["pos"]
            if acc_tokens >= target_free:
                break

        if not acc or upto_pos is None:
            return

        # стискаємо вибраний блок у 1 саммарі
        summary_rec = await summarize_block(acc)
        await insert_long_summary(chat_id, summary_rec["summary"], summary_rec["importance"], summary_rec["tokens"])
        # видаляємо старі деталі
        await delete_recent_upto_pos(chat_id, upto_pos)

    def _score(self, text: str, query: str) -> float:
        """Дуже простий скорер: частотність збігів по ключових словах."""
        if not text or not query:
            return 0.0
        import re
        q = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        if not q:
            return 0.0
        t = text.lower()
        score = 0.0
        for w in q:
            score += t.count(w)
        return score / (len(text) / 1000 + 1)

    async def _select_long_relevant(self, chat_id: int, user_query: str) -> Tuple[List[Dict[str,str]], List[int]]:
        longs = await fetch_long_all(chat_id)
        if not longs:
            return [], []
        # сорт за комбінованим критерієм: importance + релевантність
        scored = []
        for row in longs:
            s = row["summary"] or ""
            sc = self._score(s, user_query)
            final = sc * 0.7 + float(row["importance"] or 0.5) * 0.3
            scored.append((final, row))

        scored.sort(key=lambda x: x[0], reverse=True)

        selected: List[Dict[str,str]] = []
        selected_ids: List[int] = []
        budget_left = LONG_BUDGET
        for _, row in scored:
            txt = row["summary"] or ""
            t = int(row["tokens"] or 0)
            if t == 0:
                from core.tokens import count_tokens_text
                t = count_tokens_text(txt)
            if t > budget_left:
                continue
            selected.append({"role":"system", "content": f"[LONG-MEMO] {txt}"})
            selected_ids.append(int(row["id"]))
            budget_left -= t
            if budget_left <= 0:
                break
        return selected, selected_ids

    async def select_context(self, chat_id: int, user_query: str, system_prompt: str | None = None) -> List[Dict[str,str]]:
        # 1) системний
        msgs: List[Dict[str,str]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt.strip()})

        # 2) релевантні long-summary (до LONG_BUDЖЕТ)
        long_msgs, long_ids = await self._select_long_relevant(chat_id, user_query)
        msgs.extend(long_msgs)

        # 3) недавні повідомлення (повністю, але уміщаємо в RECENT_BUDЖЕТ)
        recent_rows = await fetch_recent(chat_id)
        recent_msgs = [{"role": r["role"], "content": r["content"]} for r in recent_rows]
        if count_tokens_messages(recent_msgs) > RECENT_BUDGET:
            recent_msgs = budget_trim_messages(recent_msgs, RECENT_BUDGET)
        msgs.extend(recent_msgs)

        await bump_long_usage(long_ids)

        return msgs
