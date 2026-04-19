from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .connection import execute, fetchall, fetchone
from .repositories import upsert_chat as _upsert_base_chat


async def set_chat_owner(chat_id: int, owner_account_id: int | None) -> None:
    await execute(
        """
        UPDATE chats
        SET owner_account_id = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE chat_id = %s
        """,
        (owner_account_id, chat_id),
    )


async def set_chat_type(chat_id: int, tg_chat_type: str) -> None:
    if tg_chat_type not in {"private", "group", "supergroup", "channel", "unknown"}:
        tg_chat_type = "unknown"
    await execute(
        """
        UPDATE chats
        SET tg_chat_type = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE chat_id = %s
        """,
        (tg_chat_type, chat_id),
    )


async def get_chat(chat_id: int) -> Optional[dict]:
    return await fetchone("SELECT * FROM chats WHERE chat_id=%s", (chat_id,))


async def get_chats_by_owner(owner_account_id: int) -> list[dict]:
    return await fetchall(
        "SELECT * FROM chats WHERE owner_account_id=%s ORDER BY chat_id",
        (owner_account_id,),
    ) or []


async def list_unowned_chats(limit: int = 500) -> list[dict]:
    return await fetchall(
        """
        SELECT * FROM chats
        WHERE owner_account_id IS NULL
        ORDER BY chat_id LIMIT %s
        """,
        (limit,),
    ) or []


async def ensure_chat(
    chat_id: int,
    *,
    title: str | None = None,
    lang: str | None = None,
    tg_chat_type: str | None = None,
) -> None:
    """Create/update chats row. Extends base upsert with tg_chat_type."""
    await _upsert_base_chat(chat_id, title=title, lang=lang)
    if tg_chat_type:
        await set_chat_type(chat_id, tg_chat_type)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


_VALID_ACCESS_MODES = {"open", "whitelist", "admins_only", "owner_only"}


async def get_chat_policy(chat_id: int) -> Optional[dict]:
    return await fetchone(
        "SELECT * FROM chat_policies WHERE chat_id=%s",
        (chat_id,),
    )


async def ensure_chat_policy(chat_id: int) -> dict:
    """Ensure a default policy row exists. Returns current policy."""
    existing = await get_chat_policy(chat_id)
    if existing:
        return existing
    await execute(
        "INSERT IGNORE INTO chat_policies (chat_id) VALUES (%s)",
        (chat_id,),
    )
    return await get_chat_policy(chat_id) or {}


async def update_chat_policy(
    chat_id: int,
    *,
    access_mode: str | None = None,
    per_user_daily_cap_uah: Decimal | float | int | None = None,
    per_chat_daily_cap_uah: Decimal | float | int | None = None,
    alert_threshold_pct: int | None = None,
) -> None:
    await ensure_chat_policy(chat_id)
    sets: list[str] = []
    args: list = []
    if access_mode is not None:
        if access_mode not in _VALID_ACCESS_MODES:
            raise ValueError(f"invalid access_mode: {access_mode}")
        sets.append("access_mode=%s")
        args.append(access_mode)
    if per_user_daily_cap_uah is not None:
        sets.append("per_user_daily_cap_uah=%s")
        args.append(Decimal(str(per_user_daily_cap_uah)))
    if per_chat_daily_cap_uah is not None:
        sets.append("per_chat_daily_cap_uah=%s")
        args.append(Decimal(str(per_chat_daily_cap_uah)))
    if alert_threshold_pct is not None:
        sets.append("alert_threshold_pct=%s")
        args.append(int(alert_threshold_pct))
    if not sets:
        return
    args.append(chat_id)
    sql = (
        f"UPDATE chat_policies SET {', '.join(sets)}, "
        f"updated_at=CURRENT_TIMESTAMP WHERE chat_id=%s"
    )
    await execute(sql, tuple(args))


# ---------------------------------------------------------------------------
# Access (whitelist / ban / delegated admin)
# ---------------------------------------------------------------------------


_VALID_ACCESS_ROLES = {"allowed", "banned", "delegated_admin"}


async def get_chat_access(chat_id: int, user_id: int) -> Optional[dict]:
    return await fetchone(
        "SELECT * FROM chat_access WHERE chat_id=%s AND user_id=%s",
        (chat_id, user_id),
    )


async def upsert_chat_access(
    chat_id: int,
    user_id: int,
    role: str,
    added_by: int | None = None,
) -> None:
    if role not in _VALID_ACCESS_ROLES:
        raise ValueError(f"invalid access role: {role}")
    await execute(
        """
        INSERT INTO chat_access (chat_id, user_id, role, added_by)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          role = VALUES(role),
          added_by = COALESCE(VALUES(added_by), added_by)
        """,
        (chat_id, user_id, role, added_by),
    )


async def remove_chat_access(chat_id: int, user_id: int) -> None:
    await execute(
        "DELETE FROM chat_access WHERE chat_id=%s AND user_id=%s",
        (chat_id, user_id),
    )


async def list_chat_access(chat_id: int, role: str | None = None) -> list[dict]:
    if role:
        if role not in _VALID_ACCESS_ROLES:
            raise ValueError(f"invalid role: {role}")
        return await fetchall(
            "SELECT * FROM chat_access WHERE chat_id=%s AND role=%s",
            (chat_id, role),
        ) or []
    return await fetchall(
        "SELECT * FROM chat_access WHERE chat_id=%s",
        (chat_id,),
    ) or []
