from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Optional

from .connection import execute, fetchall, fetchone


_VALID_KEY_STATUS = {"active", "disabled", "rate_limited", "invalid"}


def hash_key(raw_key: str) -> str:
    """SHA-256 hex digest of a raw API key (for dedup and logging)."""
    return hashlib.sha256((raw_key or "").encode("utf-8")).hexdigest()


async def add_provider_key(
    *,
    provider: str,
    encrypted_key: str,
    raw_key_for_hash: str,
    label: str | None = None,
    rpm_limit: int | None = None,
    tpm_limit: int | None = None,
) -> int:
    """Register a provider key. encrypted_key should already be ciphertext.

    raw_key_for_hash is used only to compute a sha256 fingerprint for dedup.
    The raw key is NOT stored anywhere after this call.
    """
    key_hash = hash_key(raw_key_for_hash)
    from .connection import get_conn_cursor
    async with get_conn_cursor() as (conn, cur):
        await cur.execute(
            """
            INSERT INTO provider_keys
              (provider, label, key_hash, encrypted_key, rpm_limit, tpm_limit, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'active')
            ON DUPLICATE KEY UPDATE
              label = COALESCE(VALUES(label), label),
              encrypted_key = VALUES(encrypted_key),
              rpm_limit = COALESCE(VALUES(rpm_limit), rpm_limit),
              tpm_limit = COALESCE(VALUES(tpm_limit), tpm_limit),
              status = CASE
                WHEN status='invalid' THEN 'invalid'
                ELSE 'active'
              END
            """,
            (provider, label, key_hash, encrypted_key, rpm_limit, tpm_limit),
        )
        key_id = cur.lastrowid or 0
        await conn.commit()
        if key_id:
            return int(key_id)
    row = await fetchone(
        "SELECT id FROM provider_keys WHERE provider=%s AND key_hash=%s",
        (provider, key_hash),
    )
    return int(row["id"]) if row else 0


async def get_provider_key(key_id: int) -> Optional[dict]:
    return await fetchone("SELECT * FROM provider_keys WHERE id=%s", (key_id,))


async def list_provider_keys(provider: str | None = None) -> list[dict]:
    if provider:
        return await fetchall(
            "SELECT * FROM provider_keys WHERE provider=%s ORDER BY id",
            (provider,),
        ) or []
    return await fetchall(
        "SELECT * FROM provider_keys ORDER BY provider, id",
    ) or []


async def pick_available_key(provider: str) -> Optional[dict]:
    """Pick an active key not in cooldown, preferring least recently used."""
    return await fetchone(
        """
        SELECT * FROM provider_keys
        WHERE provider = %s
          AND status = 'active'
          AND (cooldown_until IS NULL OR cooldown_until <= CURRENT_TIMESTAMP)
        ORDER BY
          COALESCE(last_used_at, '1970-01-01') ASC,
          total_requests ASC
        LIMIT 1
        """,
        (provider,),
    )


async def mark_key_used(
    key_id: int,
    *,
    cost_usd: Decimal | float | int = 0,
) -> None:
    await execute(
        """
        UPDATE provider_keys
        SET last_used_at = CURRENT_TIMESTAMP,
            total_requests = total_requests + 1,
            total_spent_usd = total_spent_usd + %s
        WHERE id = %s
        """,
        (Decimal(str(cost_usd)), key_id),
    )


async def mark_key_rate_limited(key_id: int, cooldown_seconds: int = 60) -> None:
    await execute(
        """
        UPDATE provider_keys
        SET status = 'rate_limited',
            cooldown_until = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL %s SECOND),
            last_error_at = CURRENT_TIMESTAMP,
            last_error = 'rate_limited'
        WHERE id = %s
        """,
        (int(cooldown_seconds), key_id),
    )


async def mark_key_error(
    key_id: int,
    error_text: str,
    *,
    disable: bool = False,
) -> None:
    new_status = "invalid" if disable else "rate_limited"
    await execute(
        """
        UPDATE provider_keys
        SET status = %s,
            last_error_at = CURRENT_TIMESTAMP,
            last_error = %s
        WHERE id = %s
        """,
        (new_status, (error_text or "")[:500], key_id),
    )


async def set_key_status(key_id: int, status: str) -> None:
    if status not in _VALID_KEY_STATUS:
        raise ValueError(f"invalid key status: {status}")
    await execute(
        """
        UPDATE provider_keys
        SET status=%s,
            cooldown_until=CASE WHEN %s='active' THEN NULL ELSE cooldown_until END
        WHERE id=%s
        """,
        (status, status, key_id),
    )


async def clear_cooldowns() -> int:
    """Reset expired cooldowns back to active. Returns affected rows."""
    from .connection import get_conn_cursor
    async with get_conn_cursor() as (_, cur):
        await cur.execute(
            """
            UPDATE provider_keys
            SET status = 'active', cooldown_until = NULL
            WHERE status = 'rate_limited'
              AND cooldown_until IS NOT NULL
              AND cooldown_until <= CURRENT_TIMESTAMP
            """,
        )
        return cur.rowcount or 0
