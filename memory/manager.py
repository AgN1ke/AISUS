from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from core.tokens import budget_trim_messages, count_tokens_messages, count_tokens_text
from db.memory_repository import (
    bump_long_usage,
    core_total_tokens,
    delete_core_all,
    delete_core_facts,
    delete_long_all,
    delete_long_by_ids,
    delete_recent_all,
    delete_recent_chat,
    delete_recent_upto_pos,
    fetch_core_all,
    fetch_core_fact,
    fetch_long_all,
    fetch_long_oldest,
    fetch_recent,
    insert_long_summary,
    insert_recent,
    long_total_tokens,
    recent_total_tokens,
    update_long_entry,
    upsert_core_fact,
)
from db.repositories import upsert_chat
from db.settings_repository import is_memory_persist_enabled

from .importance import evaluate_importance
from .summarizer import compress_entry, extract_profile_facts, summarize_block

logger = logging.getLogger(__name__)

_EMPTY_CHAT_CONTEXT_NOTICE = (
    "[CONTEXT-STATE]\n"
    "Історія цього чату зараз порожня або щойно очищена.\n"
    "Якщо користувач питає, про що ви говорили раніше, чесно скажи, що в поточному "
    "контексті попередньої розмови немає. Не вигадуй минулі повідомлення, події чи теми."
)

# Min confidence delta to overwrite an existing core fact (8% of max 320 = 25.6)
_CONFIDENCE_DELTA = 25.6
_CASCADE_BATCH_TOKENS = 500
_CONSOLIDATION_COOLDOWN_SEC = 600  # 10 minutes
_SOURCE_PRIORITY = {
    "explicit": 4,
    "llm_extracted": 3,
    "inferred": 2,
    "heuristic": 1,
    "unknown": 0,
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _recent_budget() -> int:
    return _env_int("MEMORY_RECENT_BUDGET", 5000)


def _long_budget() -> int:
    return _env_int("MEMORY_LONG_BUDGET", 30000)


def _core_budget() -> int:
    return _env_int("MEMORY_CORE_BUDGET", 1000)


def _memory_context_budget() -> int:
    return _env_int("MEMORY_CONTEXT_BUDGET", 10000)


def _working_context_budget() -> int:
    return _env_int("MEMORY_WORKING_CONTEXT_BUDGET", 5000)


def _long_context_budget() -> int:
    return _env_int(
        "MEMORY_LONG_CONTEXT_BUDGET",
        _env_int("MEMORY_LONG_RETRIEVAL_BUDGET", 4000),
    )


def _core_context_budget() -> int:
    return _env_int("MEMORY_CORE_CONTEXT_BUDGET", _core_budget())


def _compress_portion() -> float:
    return float(os.getenv("MEMORY_COMPRESS_PORTION", "0.35"))


def _dialog_model() -> str:
    return os.getenv("OPENAI_MODEL") or os.getenv("OPENAI_CHAT_MODEL") or "gpt-4o-mini"


def _normalize_memory_role(role: str | None) -> str:
    value = (role or "").strip().lower()
    if value in {"user", "assistant", "system"}:
        return value
    if value == "tool":
        return "system"
    return "system"


def _structured_fields(content: str) -> dict[str, str]:
    """Parse `key: value` lines from a service block (e.g. [CHAT-TURN])."""
    fields: dict[str, str] = {}
    for raw_line in (content or "").splitlines()[1:]:
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def _speaker_label_from_fields(fields: dict[str, str]) -> str:
    """Build a stable speaker label from CHAT-TURN fields.

    Priority: display_name → sender (already formatted) → @username → user_id.
    Falls back to empty string if none of the above is present.
    """
    name = (fields.get("sender_display_name") or "").strip()
    username = (fields.get("sender_username") or "").strip().lstrip("@")
    sender_id = (fields.get("sender_user_id") or "").strip()
    sender_combined = (fields.get("sender") or "").strip()

    if name and username:
        return f"{name} (@{username})"
    if name:
        return name
    if sender_combined:
        return sender_combined
    if username:
        return f"@{username}"
    if sender_id:
        return f"user_{sender_id}"
    return ""


def _annotate_recent_rows(rows: list[dict]) -> list[Dict[str, str]]:
    """Convert recent_rows to LLM messages with speaker labels on user turns.

    B-046/B-048 fix: in groups bot mixed up who said what because raw recent
    history was just bare role+content. The [CHAT-TURN] system block above
    each turn carried sender info but the model couldn't reliably bind that
    block to the right user message.

    Rules:
    - role stays user/assistant/system — chat_completions API needs proper
      turn structure, otherwise the model loses track of who was speaking.
    - Each [CHAT-TURN] system block is parsed; the speaker label, addressing
      flags, and reply_target preview are lifted into a `[Speaker: ...]\\n`
      header on the next user message in that turn.
    - The raw [CHAT-TURN] block is dropped from the prompt — its technical
      geometry (message_ids, timestamps) is noise for the LLM.
    - Other service blocks ([SEARCH], [LONG-MEMO], [CORE], etc.) keep
      role=system and pass through unchanged.
    """
    messages: list[Dict[str, str]] = []
    pending_speaker: str | None = None
    pending_reply_to_bot = False
    pending_addressed = False
    pending_reply_target_text: str = ""

    for row in rows:
        role = _normalize_memory_role(row.get("role"))
        content = (row.get("content") or "")
        if not content:
            continue

        if role == "system" and content.lstrip().startswith("[CHAT-TURN]"):
            fields = _structured_fields(content)
            pending_speaker = _speaker_label_from_fields(fields)
            pending_reply_to_bot = (
                (fields.get("reply_to_bot") or "").strip().lower() == "true"
            )
            pending_addressed = (
                (fields.get("addressed_via_mention") or "").strip().lower() == "true"
            )
            pending_reply_target_text = (
                fields.get("reply_target_text") or ""
            ).strip()[:240]
            # Drop the technical [CHAT-TURN] block itself from the prompt.
            continue

        if role == "user" and pending_speaker:
            header_lines = [f"[Speaker: {pending_speaker}]"]
            if pending_addressed:
                header_lines.append("addressed_via_mention: true")
            if pending_reply_to_bot:
                header_lines.append("reply_to_bot: true")
            if pending_reply_target_text:
                header_lines.append(
                    f"reply_target_text: {pending_reply_target_text}"
                )
            content = "\n".join(header_lines) + "\n\n" + content
            pending_speaker = None
            pending_reply_to_bot = False
            pending_addressed = False
            pending_reply_target_text = ""

        messages.append({"role": role, "content": content})

    return messages


def _messages_tokens(messages: List[Dict[str, str]]) -> int:
    if not messages:
        return 0
    return count_tokens_messages(messages, _dialog_model())


def _trim_messages_to_budget(
    messages: List[Dict[str, str]],
    budget: int,
) -> List[Dict[str, str]]:
    if budget <= 0 or not messages:
        return []
    if _messages_tokens(messages) <= budget:
        return messages
    return budget_trim_messages(messages, budget, _dialog_model())


def _fit_lines_to_budget(prefix: str, lines: List[str], budget: int) -> str:
    if budget <= 0 or not lines:
        return ""
    selected: List[str] = []
    for line in lines:
        candidate_lines = [*selected, line]
        text = f"{prefix}\n" + "\n".join(candidate_lines)
        if count_tokens_text(text, _dialog_model()) > budget:
            break
        selected.append(line)
    if selected:
        return "\n".join(selected)
    clipped = lines[0].strip()
    while clipped:
        text = f"{prefix}\n{clipped}"
        if count_tokens_text(text, _dialog_model()) <= budget:
            return clipped
        clipped = clipped[: max(0, len(clipped) * 3 // 4)].strip()
    return ""


def _source_priority(source: str | None) -> int:
    return _SOURCE_PRIORITY.get((source or "unknown").strip(), 0)


def _stable_participant_ids_from_block(block_text: str) -> set[str]:
    ids: set[str] = set()
    for value in re.findall(
        r"(?im)^\s*(?:sender_user_id|reply_target_author_user_id):\s*(\d+)\s*$",
        block_text or "",
    ):
        ids.add(f"user_{value}")
    for value in re.findall(
        r"(?im)^\s*(?:sender_username|reply_target_author_username):\s*@?([A-Za-z0-9_]{3,64})\s*$",
        block_text or "",
    ):
        ids.add(value.lower())
    return ids


def _participant_fact_stable_id(key: str) -> str | None:
    match = re.match(r"^participant\.([A-Za-z0-9_]+)\.", (key or "").strip())
    if not match:
        return None
    return match.group(1).lower()


def _is_safe_participant_fact(key: str, block_text: str) -> bool:
    key = (key or "").strip()
    if not key.startswith("participant."):
        return True
    stable_id = _participant_fact_stable_id(key)
    if not stable_id:
        return False
    return stable_id in _stable_participant_ids_from_block(block_text)


def _should_replace_core_fact(
    existing: dict | None,
    *,
    source: str,
    confidence: float,
    value: str,
) -> bool:
    if not existing:
        return True

    old_value = str(existing.get("fact_value") or "").strip()
    old_source = str(existing.get("source") or "unknown").strip()
    old_confidence = float(existing.get("confidence") or 0)

    if source == "explicit" and value and value != old_value:
        return True

    new_priority = _source_priority(source)
    old_priority = _source_priority(old_source)
    if new_priority > old_priority:
        return True
    if new_priority < old_priority:
        return False
    return confidence - old_confidence >= _CONFIDENCE_DELTA


class MemoryManager:

    def __init__(self):
        self._locks: Dict[int, asyncio.Lock] = {}
        self._last_consolidation: Dict[int, float] = {}

    def _lock_for(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def _ensure_chat(self, chat_id: int):
        await upsert_chat(chat_id, title=None, lang=None)

    async def append_message(self, chat_id: int, role: str, content: str):
        await self._ensure_chat(chat_id)
        role = _normalize_memory_role(role)
        tokens = count_tokens_text(content, _dialog_model())
        await insert_recent(chat_id, role, content, tokens)

    # ------------------------------------------------------------------
    # CORE context helper
    # ------------------------------------------------------------------

    async def _core_context_text(self, chat_id: int) -> str:
        """Format CORE facts as plain text for prompts."""
        facts = await fetch_core_all(chat_id)
        if not facts:
            return ""
        lines = [f"{f['fact_key']}: {f['fact_value']}" for f in facts]
        return "\n".join(lines)

    async def _core_context_message(
        self, chat_id: int, budget: int
    ) -> tuple[dict[str, str] | None, int]:
        """Format CORE for prompt context, capped by the core context budget."""
        facts = await fetch_core_all(chat_id)
        if not facts or budget <= 0:
            return None, 0
        lines = [f"{f['fact_key']}: {f['fact_value']}" for f in facts]
        text = _fit_lines_to_budget("[CORE]", lines, budget)
        if not text:
            return None, 0
        msg = {"role": "system", "content": f"[CORE]\n{text}"}
        return msg, _messages_tokens([msg])

    # ------------------------------------------------------------------
    # Profile fact extraction & storage
    # ------------------------------------------------------------------

    async def _save_profile_facts(
        self, chat_id: int, block_text: str, core_context: str
    ):
        """Extract and upsert profile facts from a conversation block."""
        facts = await extract_profile_facts(block_text, core_context)
        if not facts:
            return

        core_budget = _core_budget()
        current_tokens = await core_total_tokens(chat_id)

        for fact in facts:
            key = fact.get("key", "").strip()
            value = fact.get("value", "").strip()
            if not key or not value:
                continue
            if not _is_safe_participant_fact(key, block_text):
                logger.debug(
                    "core.participant_fact_rejected chat=%s key=%s",
                    chat_id,
                    key,
                )
                continue

            source = fact.get("source", "unknown")
            confidence = float(fact.get("confidence", 100))
            tokens = count_tokens_text(f"{key}: {value}", _dialog_model())

            # Check if fact already exists — enforce confidence delta
            existing = await fetch_core_fact(chat_id, key)
            if existing:
                if not _should_replace_core_fact(
                    existing,
                    source=source,
                    confidence=confidence,
                    value=value,
                ):
                    continue
                # Replacing: tokens don't increase net usage
            else:
                # New fact: check budget
                if current_tokens + tokens > core_budget:
                    logger.debug(
                        "core.budget_exceeded chat=%s key=%s, skipping", chat_id, key
                    )
                    continue
                current_tokens += tokens

            # Reject empty/placeholder values
            if value.lower() in {"null", "unknown", "?", "–", "-", "none", ""}:
                continue

            await upsert_core_fact(chat_id, key, value, source, confidence, tokens)

    # ------------------------------------------------------------------
    # Cascading recompression
    # ------------------------------------------------------------------

    async def _cascade_recompress(self, chat_id: int, needed_space: int):
        """Free up needed_space tokens in Long-term via cascading recompression."""
        freed = 0
        core_ctx = await self._core_context_text(chat_id)
        max_passes = 6  # safety limit

        for pass_num in range(max_passes):
            batch = await fetch_long_oldest(chat_id, _CASCADE_BATCH_TOKENS)
            if not batch:
                break

            # Separate protected entries
            compressible = [r for r in batch if not r.get("is_core_memory")]
            if not compressible:
                break

            now = datetime.now(timezone.utc)
            entries_for_eval = []
            for r in compressible:
                created = r.get("created_at")
                if created and hasattr(created, "timestamp"):
                    age_days = (now - created.replace(tzinfo=timezone.utc)).days
                else:
                    age_days = 0
                entries_for_eval.append({
                    "id": r["id"],
                    "text": r["summary"],
                    "age_days": age_days,
                    "is_core_memory": False,
                })

            evaluations = await evaluate_importance(entries_for_eval, core_ctx)
            eval_map = {e["id"]: e for e in evaluations}

            ids_to_delete = []
            for r in compressible:
                ev = eval_map.get(r["id"])
                if not ev:
                    continue
                imp = ev["importance"]
                old_tokens = int(r.get("tokens") or 0)

                if imp <= 3:
                    ids_to_delete.append(r["id"])
                    freed += old_tokens
                elif imp <= 6:
                    compressed = ev.get("compressed_text")
                    if not compressed:
                        compressed = await compress_entry(r["summary"], core_ctx)
                    new_tokens = count_tokens_text(compressed, _dialog_model())
                    if new_tokens < old_tokens:
                        await update_long_entry(
                            r["id"], compressed, ev["importance"] / 10.0, new_tokens
                        )
                        freed += old_tokens - new_tokens
                # importance 7+: keep as-is

            if ids_to_delete:
                await delete_long_by_ids(ids_to_delete)

            if freed >= needed_space:
                break

        # Fallback: if still not enough, raise threshold and delete
        if freed < needed_space:
            logger.warning(
                "cascade.fallback chat=%s freed=%d needed=%d, using FIFO",
                chat_id, freed, needed_space,
            )
            remaining = needed_space - freed
            oldest = await fetch_long_oldest(chat_id, remaining + 200)
            ids_fifo = []
            fifo_freed = 0
            for r in oldest:
                if r.get("is_core_memory"):
                    continue
                ids_fifo.append(r["id"])
                fifo_freed += int(r.get("tokens") or 0)
                if fifo_freed >= remaining:
                    break
            if ids_fifo:
                await delete_long_by_ids(ids_fifo)

    # ------------------------------------------------------------------
    # Budget enforcement
    # ------------------------------------------------------------------

    async def ensure_budget(self, chat_id: int):
        await self._ensure_chat(chat_id)

        # Cooldown check
        now_ts = asyncio.get_event_loop().time()
        last = self._last_consolidation.get(chat_id, 0)
        if now_ts - last < _CONSOLIDATION_COOLDOWN_SEC:
            # Still trim recent if needed (without LLM calls)
            return

        async with self._lock_for(chat_id):
            persist = await is_memory_persist_enabled(chat_id)
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
                acc.append({
                    "role": _normalize_memory_role(row["role"]),
                    "content": row["content"],
                })
                acc_tokens += int(row["tokens"])
                upto_pos = row["pos"]
                if acc_tokens >= target_free:
                    break

            if not acc or upto_pos is None:
                return

            summary_rec = await summarize_block(acc)

            if persist:
                # Save to long-term
                await insert_long_summary(
                    chat_id,
                    summary_rec["summary"],
                    summary_rec["importance"],
                    summary_rec["tokens"],
                )

                # Extract and save profile facts to CORE
                block_text = "\n".join(
                    f"{m['role']}: {m['content']}" for m in acc
                )
                core_ctx = await self._core_context_text(chat_id)
                await self._save_profile_facts(chat_id, block_text, core_ctx)

                # Check if long-term needs cascade recompression
                lt_total = await long_total_tokens(chat_id)
                lt_budget = _long_budget()
                if lt_total > lt_budget:
                    needed = lt_total - lt_budget
                    await self._cascade_recompress(chat_id, needed)

            # Always delete compressed recent messages
            await delete_recent_upto_pos(chat_id, upto_pos)
            self._last_consolidation[chat_id] = now_ts

    # ------------------------------------------------------------------
    # Relevance scoring for Long-term retrieval
    # ------------------------------------------------------------------

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
        self, chat_id: int, user_query: str, budget: int | None = None
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
        budget_left = _long_context_budget() if budget is None else max(0, budget)
        for _, row in scored:
            text = row["summary"] or ""
            tokens = int(row["tokens"] or 0)
            if tokens == 0:
                tokens = count_tokens_text(text, _dialog_model())
            if tokens > budget_left:
                continue
            selected.append({"role": "system", "content": f"[LONG-MEMO] {text}"})
            selected_ids.append(int(row["id"]))
            budget_left -= tokens
            if budget_left <= 0:
                break
        return selected, selected_ids

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    async def select_context(
        self, chat_id: int, user_query: str, system_prompt: str | None = None
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        has_memory = False
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt.strip()})

        persist = await is_memory_persist_enabled(chat_id)
        total_budget = max(0, _memory_context_budget())
        reserved_tokens = _messages_tokens(messages)
        memory_budget_left = max(0, total_budget - reserved_tokens)
        core_tokens = 0

        if persist:
            # CORE layer — always included fully
            core_msg, core_tokens = await self._core_context_message(
                chat_id,
                min(_core_context_budget(), memory_budget_left),
            )
            if core_msg:
                has_memory = True
                messages.append(core_msg)
                memory_budget_left = max(0, memory_budget_left - core_tokens)

            # Long-term — relevance-scored selection
            long_msgs, long_ids = await self._select_long_relevant(chat_id, user_query)
            if long_msgs:
                has_memory = True
            messages.extend(long_msgs)
        else:
            long_ids = []

        # Recent / Working layer — always included.
        # Each user turn is prefixed with [Speaker: ...] so the model knows
        # who exactly said what (critical in groups), while the raw
        # [CHAT-TURN] technical block is dropped from the prompt.
        recent_rows = await fetch_recent(chat_id)
        recent_msgs = _annotate_recent_rows(recent_rows)
        recent_budget = _working_context_budget()
        if _messages_tokens(recent_msgs) > recent_budget:
            recent_msgs = _trim_messages_to_budget(recent_msgs, recent_budget)
        if recent_msgs:
            has_memory = True
        messages.extend(recent_msgs)

        if not has_memory:
            messages.append(
                {
                    "role": "system",
                    "content": _EMPTY_CHAT_CONTEXT_NOTICE,
                }
            )

        if long_ids:
            await bump_long_usage(long_ids)
        return messages

    # ------------------------------------------------------------------
    # Clear all memory for a chat
    # ------------------------------------------------------------------

    async def clear_all(self, chat_id: int):
        """Clear all memory layers for a chat, including working/recent context."""
        await delete_recent_chat(chat_id)
        await delete_core_facts(chat_id)
        all_long = await fetch_long_all(chat_id)
        if all_long:
            await delete_long_by_ids([int(r["id"]) for r in all_long])
        self._last_consolidation.pop(chat_id, None)

    async def clear_global(self):
        """Clear all memory layers for all chats."""
        await delete_recent_all()
        await delete_long_all()
        await delete_core_all()
        self._last_consolidation.clear()
