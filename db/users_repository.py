from __future__ import annotations

from typing import Optional

from .connection import execute, fetchone


async def upsert_user(
    user_id: int,
    tg_username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    lang_code: str | None = None,
) -> None:
    await execute(
        """
        INSERT INTO users (user_id, tg_username, first_name, last_name, lang_code)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          tg_username = COALESCE(VALUES(tg_username), tg_username),
          first_name = COALESCE(VALUES(first_name), first_name),
          last_name = COALESCE(VALUES(last_name), last_name),
          lang_code = COALESCE(VALUES(lang_code), lang_code),
          last_seen_at = CURRENT_TIMESTAMP
        """,
        (user_id, tg_username, first_name, last_name, lang_code),
    )


async def get_user(user_id: int) -> Optional[dict]:
    return await fetchone("SELECT * FROM users WHERE user_id=%s", (user_id,))


async def get_user_by_username(username: str) -> Optional[dict]:
    clean = (username or "").lstrip("@").strip()
    if not clean:
        return None
    return await fetchone(
        "SELECT * FROM users WHERE tg_username=%s LIMIT 1",
        (clean,),
    )


async def set_user_setting(user_id: int, key: str, value: str | None) -> None:
    await execute(
        """
        INSERT INTO user_settings (user_id, setting_key, setting_value)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
          setting_value = VALUES(setting_value),
          updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, key, value),
    )


async def get_user_setting(user_id: int, key: str) -> Optional[str]:
    row = await fetchone(
        "SELECT setting_value FROM user_settings WHERE user_id=%s AND setting_key=%s",
        (user_id, key),
    )
    if not row:
        return None
    return row.get("setting_value")


async def get_user_settings(user_id: int) -> dict[str, str]:
    from .connection import fetchall

    rows = await fetchall(
        "SELECT setting_key, setting_value FROM user_settings WHERE user_id=%s",
        (user_id,),
    )
    return {row["setting_key"]: row["setting_value"] for row in rows or []}
