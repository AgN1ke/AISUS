from __future__ import annotations
from typing import Iterable, Dict, Any, List, Tuple, Optional
from .connection import execute, fetchall, fetchone

# RECENT

async def insert_recent(chat_id: int, role: str, content: str, tokens: int):
    sql = """
    INSERT INTO memory_recent (chat_id, role, content, tokens)
    VALUES (%s, %s, %s, %s)
    """
    await execute(sql, (chat_id, role, content, tokens))

async def fetch_recent(chat_id: int, limit: int | None = None) -> list[dict]:
    base = "SELECT pos, role, content, tokens, created_at FROM memory_recent WHERE chat_id=%s ORDER BY pos ASC"
    if limit:
        base += f" LIMIT {int(limit)}"
    rows = await fetchall(base, (chat_id,))
    return rows or []

async def recent_total_tokens(chat_id: int) -> int:
    row = await fetchone("SELECT COALESCE(SUM(tokens),0) AS t FROM memory_recent WHERE chat_id=%s", (chat_id,))
    return int(row["t"]) if row else 0

async def delete_recent_upto_pos(chat_id: int, upto_pos: int):
    await execute("DELETE FROM memory_recent WHERE chat_id=%s AND pos<=%s", (chat_id, upto_pos))

# LONG

async def insert_long_summary(chat_id: int, summary: str, importance: float, tokens: int):
    sql = """
    INSERT INTO memory_long (chat_id, summary, importance, usage_count, last_used, tokens)
    VALUES (%s, %s, %s, 0, NOW(), %s)
    """
    await execute(sql, (chat_id, summary, float(importance), tokens))

async def fetch_long_all(chat_id: int) -> list[dict]:
    return await fetchall("""
    SELECT id, summary, importance, usage_count, last_used, tokens
    FROM memory_long
    WHERE chat_id=%s
    ORDER BY importance DESC, COALESCE(last_used,'1970-01-01') DESC
    """, (chat_id,))

async def bump_long_usage(ids: Iterable[int]):
    ids = list(ids)
    if not ids:
        return
    placeholders = ",".join(["%s"] * len(ids))
    await execute(f"UPDATE memory_long SET usage_count=usage_count+1, last_used=NOW() WHERE id IN ({placeholders})", ids)
