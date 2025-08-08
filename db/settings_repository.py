from __future__ import annotations
from typing import Optional
from .connection import fetchone, execute

async def get_settings(chat_id: int) -> Optional[dict]:
    return await fetchone("SELECT * FROM settings WHERE chat_id=%s", (chat_id,))

async def upsert_settings(chat_id: int, auth_ok: bool | None = None, mode: str | None = None):
    await execute(
        """
        INSERT INTO settings (chat_id, auth_ok, mode)
        VALUES (%s, COALESCE(%s, 0), COALESCE(%s,'bot'))
        ON DUPLICATE KEY UPDATE
          auth_ok = COALESCE(VALUES(auth_ok), auth_ok),
          mode = COALESCE(VALUES(mode), mode),
          updated_at = CURRENT_TIMESTAMP
        """,
        (chat_id, auth_ok, mode),
    )
