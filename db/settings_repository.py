from __future__ import annotations

import json
from typing import Optional

from .connection import execute, fetchone
from .repositories import upsert_chat


async def get_settings(chat_id: int) -> Optional[dict]:
    return await fetchone("SELECT * FROM settings WHERE chat_id=%s", (chat_id,))


async def upsert_settings(
    chat_id: int,
    auth_ok: bool | None = None,
    mode: str | None = None,
    memory_persist_enabled: bool | None = None,
):
    await upsert_chat(chat_id, title=None, lang=None)
    await execute(
        """
        INSERT INTO settings (chat_id, auth_ok, mode, memory_persist_enabled)
        VALUES (%s, COALESCE(%s, 0), COALESCE(%s,'bot'), COALESCE(%s, 1))
        ON DUPLICATE KEY UPDATE
          auth_ok = COALESCE(VALUES(auth_ok), auth_ok),
          mode = COALESCE(VALUES(mode), mode),
          memory_persist_enabled = COALESCE(VALUES(memory_persist_enabled), memory_persist_enabled),
          updated_at = CURRENT_TIMESTAMP
        """,
        (chat_id, auth_ok, mode, memory_persist_enabled),
    )


async def is_memory_persist_enabled(chat_id: int) -> bool:
    row = await fetchone(
        "SELECT memory_persist_enabled FROM settings WHERE chat_id=%s",
        (chat_id,),
    )
    if not row:
        return True
    return bool(row.get("memory_persist_enabled", 1))


async def set_last_reflection(chat_id: int):
    await execute(
        "UPDATE settings SET last_reflection_at=NOW() WHERE chat_id=%s",
        (chat_id,),
    )


async def get_last_reflection(chat_id: int) -> Optional[object]:
    row = await fetchone(
        "SELECT last_reflection_at FROM settings WHERE chat_id=%s",
        (chat_id,),
    )
    return row["last_reflection_at"] if row else None


async def get_podcast_pending(chat_id: int) -> Optional[dict]:
    row = await fetchone(
        "SELECT podcast_pending_json FROM settings WHERE chat_id=%s",
        (chat_id,),
    )
    if not row:
        return None
    raw = (row.get("podcast_pending_json") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


async def set_podcast_pending(chat_id: int, payload: dict) -> None:
    await upsert_chat(chat_id, title=None, lang=None)
    rendered = json.dumps(payload, ensure_ascii=False)
    await execute(
        """
        INSERT INTO settings (chat_id, podcast_pending_json, podcast_pending_created_at)
        VALUES (%s, %s, NOW())
        ON DUPLICATE KEY UPDATE
          podcast_pending_json = VALUES(podcast_pending_json),
          podcast_pending_created_at = NOW(),
          updated_at = CURRENT_TIMESTAMP
        """,
        (chat_id, rendered),
    )


async def clear_podcast_pending(chat_id: int) -> None:
    await execute(
        """
        UPDATE settings
        SET podcast_pending_json = NULL,
            podcast_pending_created_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE chat_id=%s
        """,
        (chat_id,),
    )


async def get_podcast_dossier(chat_id: int) -> Optional[dict]:
    row = await fetchone(
        "SELECT podcast_dossier_json FROM settings WHERE chat_id=%s",
        (chat_id,),
    )
    if not row:
        return None
    raw = (row.get("podcast_dossier_json") or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


async def set_podcast_dossier(chat_id: int, payload: dict) -> None:
    await upsert_chat(chat_id, title=None, lang=None)
    rendered = json.dumps(payload, ensure_ascii=False)
    await execute(
        """
        INSERT INTO settings (chat_id, podcast_dossier_json, podcast_dossier_created_at)
        VALUES (%s, %s, NOW())
        ON DUPLICATE KEY UPDATE
          podcast_dossier_json = VALUES(podcast_dossier_json),
          podcast_dossier_created_at = NOW(),
          updated_at = CURRENT_TIMESTAMP
        """,
        (chat_id, rendered),
    )


async def clear_podcast_dossier(chat_id: int) -> None:
    await execute(
        """
        UPDATE settings
        SET podcast_dossier_json = NULL,
            podcast_dossier_created_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE chat_id=%s
        """,
        (chat_id,),
    )
