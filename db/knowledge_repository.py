# db/knowledge_repository.py
from __future__ import annotations
from typing import Optional, Iterable, List, Dict
from .connection import execute, fetchone, fetchall

# ---- MESSAGES ----
async def insert_message(chat_id: int, msg_id: int, user_id: Optional[int],
                         kind: str, text: Optional[str], caption_text: Optional[str],
                         has_media: bool, thread_root_msg_id: Optional[int]):
    sql = """
    INSERT INTO messages (chat_id, msg_id, user_id, kind, text, caption_text, has_media, thread_root_msg_id)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      user_id=VALUES(user_id),
      kind=VALUES(kind),
      text=VALUES(text),
      caption_text=VALUES(caption_text),
      has_media=VALUES(has_media),
      thread_root_msg_id=VALUES(thread_root_msg_id),
      created_at=created_at
    """
    await execute(sql, (chat_id, msg_id, user_id, kind, text, caption_text, int(bool(has_media)), thread_root_msg_id))

async def get_message(chat_id: int, msg_id: int) -> Optional[dict]:
    return await fetchone("SELECT * FROM messages WHERE chat_id=%s AND msg_id=%s", (chat_id, msg_id))

async def fetch_thread_messages(chat_id: int, root_id: int, limit: int = 20) -> List[dict]:
    return await fetchall("""
    SELECT msg_id, user_id, kind, text, caption_text, created_at
    FROM messages
    WHERE chat_id=%s AND thread_root_msg_id=%s
    ORDER BY created_at DESC
    LIMIT %s
    """, (chat_id, root_id, int(limit)))

# ---- THREADS ----
async def upsert_thread(chat_id: int, root_msg_id: int):
    sql = """
    INSERT INTO threads (chat_id, thread_root_msg_id, topic_summary)
    VALUES (%s, %s, NULL)
    ON DUPLICATE KEY UPDATE
      last_msg_at = CURRENT_TIMESTAMP
    """
    await execute(sql, (chat_id, root_msg_id))

async def get_thread(chat_id: int, root_msg_id: int) -> Optional[dict]:
    return await fetchone("""
    SELECT chat_id, thread_root_msg_id, topic_summary, started_at, last_msg_at
    FROM threads WHERE chat_id=%s AND thread_root_msg_id=%s
    """, (chat_id, root_msg_id))

async def set_thread_summary(chat_id: int, root_msg_id: int, summary: str):
    await execute("""
    UPDATE threads SET topic_summary=%s, last_msg_at=CURRENT_TIMESTAMP
    WHERE chat_id=%s AND thread_root_msg_id=%s
    """, (summary, chat_id, root_msg_id))

# ---- GLOSSARY ----
async def upsert_term(chat_id: int, term: str, inc: int = 1):
    sql = """
    INSERT INTO glossary (chat_id, term, usage_count, last_used, status)
    VALUES (%s,%s,%s,NOW(),'new')
    ON DUPLICATE KEY UPDATE
      usage_count = usage_count + VALUES(usage_count),
      last_used = NOW()
    """
    await execute(sql, (chat_id, term, int(inc)))

async def get_term(chat_id: int, term: str) -> Optional[dict]:
    return await fetchone("SELECT * FROM glossary WHERE chat_id=%s AND term=%s", (chat_id, term))

async def fetch_gc_candidates(chat_id: int, idle_days: int = 30, limit: int = 10) -> List[dict]:
    return await fetchall("""
    SELECT term, usage_count, last_used, status
    FROM glossary
    WHERE chat_id=%s AND status!='archived' AND (last_used IS NULL OR last_used < NOW() - INTERVAL %s DAY)
    ORDER BY last_used ASC
    LIMIT %s
    """, (chat_id, int(idle_days), int(limit)))
