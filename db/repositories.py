# db/repositories.py
from datetime import datetime
from .connection import execute

async def upsert_chat(chat_id: int, title: str | None, lang: str | None):
    sql = """
    INSERT INTO chats (chat_id, title, lang)
    VALUES (%s, %s, %s)
    ON DUPLICATE KEY UPDATE
      title = VALUES(title),
      lang = VALUES(lang),
      updated_at = CURRENT_TIMESTAMP
    """
    await execute(sql, (chat_id, title, lang))

async def upsert_participant(chat_id: int, user_id: int, username: str | None, display_name: str | None, role: str | None = None):
    sql = """
    INSERT INTO participants (chat_id, user_id, username, display_name, role, last_active, messages_count)
    VALUES (%s, %s, %s, %s, %s, NOW(), 1)
    ON DUPLICATE KEY UPDATE
      username = VALUES(username),
      display_name = VALUES(display_name),
      role = COALESCE(VALUES(role), role),
      last_active = NOW(),
      messages_count = messages_count + 1
    """
    await execute(sql, (chat_id, user_id, username, display_name, role))
