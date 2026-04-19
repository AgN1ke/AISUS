from __future__ import annotations

import json
from decimal import Decimal
from typing import Optional

from .connection import execute, fetchall, fetchone


_VALID_TOPUP_STATUS = {
    "created", "pending", "success", "expired", "failed", "manual",
}


async def create_topup(
    *,
    account_id: int,
    amount_uah: Decimal | float | int,
    monopay_invoice_id: str | None = None,
    monopay_url: str | None = None,
    status: str = "created",
    note: str | None = None,
) -> int:
    if status not in _VALID_TOPUP_STATUS:
        raise ValueError(f"invalid topup status: {status}")
    from .connection import get_conn_cursor
    async with get_conn_cursor() as (conn, cur):
        await cur.execute(
            """
            INSERT INTO topups
              (account_id, amount_uah, monopay_invoice_id, monopay_url, status, note)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                account_id,
                Decimal(str(amount_uah)),
                monopay_invoice_id,
                monopay_url,
                status,
                (note or "")[:255] if note else None,
            ),
        )
        topup_id = cur.lastrowid
        await conn.commit()
        return int(topup_id)


async def get_topup(topup_id: int) -> Optional[dict]:
    return await fetchone("SELECT * FROM topups WHERE id=%s", (topup_id,))


async def get_topup_by_invoice(invoice_id: str) -> Optional[dict]:
    return await fetchone(
        "SELECT * FROM topups WHERE monopay_invoice_id=%s",
        (invoice_id,),
    )


async def list_topups_for_account(
    account_id: int, limit: int = 50
) -> list[dict]:
    return await fetchall(
        """
        SELECT * FROM topups
        WHERE account_id=%s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (account_id, limit),
    ) or []


async def list_pending_topups() -> list[dict]:
    return await fetchall(
        "SELECT * FROM topups WHERE status IN ('created','pending')",
    ) or []


async def update_topup_status(
    topup_id: int,
    status: str,
    *,
    webhook_payload: dict | None = None,
) -> None:
    if status not in _VALID_TOPUP_STATUS:
        raise ValueError(f"invalid topup status: {status}")
    payload_json = json.dumps(webhook_payload, ensure_ascii=False) if webhook_payload else None
    paid_marker = "paid_at = CURRENT_TIMESTAMP," if status == "success" else ""
    await execute(
        f"""
        UPDATE topups
        SET status = %s,
            {paid_marker}
            webhook_payload = COALESCE(%s, webhook_payload)
        WHERE id = %s
        """,
        (status, payload_json, topup_id),
    )
