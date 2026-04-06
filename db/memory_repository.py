from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional, Tuple
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


async def long_total_tokens(chat_id: int) -> int:
    row = await fetchone(
        "SELECT COALESCE(SUM(tokens),0) AS t FROM memory_long WHERE chat_id=%s",
        (chat_id,),
    )
    return int(row["t"]) if row else 0


async def fetch_long_oldest(chat_id: int, token_limit: int = 500) -> list[dict]:
    """Fetch oldest long-term entries up to ~token_limit tokens total."""
    rows = await fetchall(
        """
        SELECT id, summary, importance, tokens, is_core_memory, created_at
        FROM memory_long
        WHERE chat_id=%s
        ORDER BY created_at ASC
        """,
        (chat_id,),
    )
    result = []
    acc = 0
    for row in rows:
        t = int(row.get("tokens") or 0)
        if acc + t > token_limit and result:
            break
        result.append(row)
        acc += t
    return result


async def delete_long_by_ids(ids: list[int]):
    if not ids:
        return
    placeholders = ",".join(["%s"] * len(ids))
    await execute(
        f"DELETE FROM memory_long WHERE id IN ({placeholders})", ids
    )


async def update_long_entry(entry_id: int, summary: str, importance: float, tokens: int):
    await execute(
        "UPDATE memory_long SET summary=%s, importance=%s, tokens=%s WHERE id=%s",
        (summary, float(importance), tokens, entry_id),
    )


# CORE

async def fetch_core_all(chat_id: int) -> list[dict]:
    return await fetchall(
        "SELECT id, fact_key, fact_value, source, confidence, tokens FROM memory_core WHERE chat_id=%s ORDER BY created_at ASC",
        (chat_id,),
    ) or []


async def core_total_tokens(chat_id: int) -> int:
    row = await fetchone(
        "SELECT COALESCE(SUM(tokens),0) AS t FROM memory_core WHERE chat_id=%s",
        (chat_id,),
    )
    return int(row["t"]) if row else 0


async def upsert_core_fact(
    chat_id: int, fact_key: str, fact_value: str,
    source: str, confidence: float, tokens: int,
):
    await execute(
        """
        INSERT INTO memory_core (chat_id, fact_key, fact_value, source, confidence, tokens)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          fact_value = VALUES(fact_value),
          source = VALUES(source),
          confidence = VALUES(confidence),
          tokens = VALUES(tokens),
          updated_at = CURRENT_TIMESTAMP
        """,
        (chat_id, fact_key, fact_value, source, float(confidence), tokens),
    )


async def delete_core_facts(chat_id: int):
    await execute("DELETE FROM memory_core WHERE chat_id=%s", (chat_id,))


async def fetch_core_fact(chat_id: int, fact_key: str) -> Optional[dict]:
    return await fetchone(
        "SELECT fact_key, fact_value, source, confidence, tokens FROM memory_core WHERE chat_id=%s AND fact_key=%s",
        (chat_id, fact_key),
    )


async def fetch_chats_with_recent() -> list[int]:
    rows = await fetchall("SELECT DISTINCT chat_id FROM memory_recent")
    return [int(r["chat_id"]) for r in rows] if rows else []
