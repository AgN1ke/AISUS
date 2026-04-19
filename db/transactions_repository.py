from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from .connection import execute, fetchall, fetchone


_VALID_TURN_STATUS = {
    "running", "completed", "failed", "budget_blocked", "policy_blocked",
}
_VALID_TX_KIND = {"llm_call", "search_api", "tts", "stt", "fetch_page", "other"}
_VALID_TX_STATUS = {"success", "failed", "rate_limited"}


def new_turn_id() -> str:
    return str(uuid.uuid4())


async def create_turn(
    *,
    account_id: int,
    chat_id: int,
    user_id: int,
    tg_message_id: int | None = None,
    user_message_text: str | None = None,
    turn_id: str | None = None,
) -> str:
    turn_id = turn_id or new_turn_id()
    await execute(
        """
        INSERT INTO turns (
          turn_id, account_id, chat_id, user_id,
          tg_message_id, user_message_text, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'running')
        """,
        (
            turn_id, account_id, chat_id, user_id,
            tg_message_id, (user_message_text or "")[:2000],
        ),
    )
    return turn_id


async def finalize_turn(
    turn_id: str,
    *,
    status: str = "completed",
    route: str | None = None,
    capability: str | None = None,
) -> None:
    if status not in _VALID_TURN_STATUS:
        raise ValueError(f"invalid turn status: {status}")
    await execute(
        """
        UPDATE turns t
        SET status = %s,
            route = COALESCE(%s, route),
            capability = COALESCE(%s, capability),
            total_cost_uah = COALESCE(
              (SELECT SUM(cost_uah) FROM transactions WHERE turn_id=t.turn_id),
              0
            ),
            completed_at = CURRENT_TIMESTAMP
        WHERE t.turn_id = %s
        """,
        (status, route, capability, turn_id),
    )


async def get_turn(turn_id: str) -> Optional[dict]:
    return await fetchone("SELECT * FROM turns WHERE turn_id=%s", (turn_id,))


async def get_latest_turn_for_account(account_id: int) -> Optional[dict]:
    return await fetchone(
        """
        SELECT * FROM turns
        WHERE account_id=%s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (account_id,),
    )


async def find_turns_for_account(account_id: int, turn_ref: str, limit: int = 5) -> list[dict]:
    normalized = (turn_ref or "").strip()
    if not normalized:
        return []
    return await fetchall(
        """
        SELECT * FROM turns
        WHERE account_id=%s
          AND turn_id LIKE %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (account_id, f"{normalized}%", limit),
    ) or []


async def list_turns_for_account(
    account_id: int, limit: int = 20
) -> list[dict]:
    return await fetchall(
        """
        SELECT * FROM turns
        WHERE account_id=%s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (account_id, limit),
    ) or []


async def log_transaction(
    *,
    turn_id: str | None,
    account_id: int,
    chat_id: int,
    user_id: int,
    kind: str = "llm_call",
    capability: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    unit_count: int = 0,
    cost_usd: Decimal | float = 0,
    cost_uah: Decimal | float = 0,
    markup_pct: Decimal | float = 0,
    key_id: int | None = None,
    latency_ms: int | None = None,
    status: str = "success",
    error_text: str | None = None,
) -> int:
    if kind not in _VALID_TX_KIND:
        raise ValueError(f"invalid tx kind: {kind}")
    if status not in _VALID_TX_STATUS:
        raise ValueError(f"invalid tx status: {status}")
    from .connection import get_conn_cursor
    async with get_conn_cursor() as (conn, cur):
        await cur.execute(
            """
            INSERT INTO transactions (
              turn_id, account_id, chat_id, user_id,
              kind, capability, provider, model,
              tokens_in, tokens_out, unit_count,
              cost_usd, cost_uah, markup_pct,
              key_id, latency_ms, status, error_text
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                turn_id, account_id, chat_id, user_id,
                kind, capability, provider, model,
                int(tokens_in), int(tokens_out), int(unit_count),
                Decimal(str(cost_usd)), Decimal(str(cost_uah)), Decimal(str(markup_pct)),
                key_id, latency_ms, status,
                (error_text or "")[:1000] if error_text else None,
            ),
        )
        tx_id = cur.lastrowid
        await conn.commit()
        return int(tx_id)


async def get_transactions_for_turn(turn_id: str) -> list[dict]:
    return await fetchall(
        "SELECT * FROM transactions WHERE turn_id=%s ORDER BY id ASC",
        (turn_id,),
    ) or []


async def get_recent_transactions(
    account_id: int, limit: int = 50
) -> list[dict]:
    return await fetchall(
        """
        SELECT * FROM transactions
        WHERE account_id=%s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (account_id, limit),
    ) or []


async def sum_user_spent_today(chat_id: int, user_id: int) -> Decimal:
    row = await fetchone(
        """
        SELECT COALESCE(SUM(cost_uah), 0) AS total
        FROM transactions
        WHERE chat_id=%s AND user_id=%s
          AND created_at >= CURDATE()
        """,
        (chat_id, user_id),
    )
    return Decimal(str(row["total"] if row else 0))


async def sum_chat_spent_today(chat_id: int) -> Decimal:
    row = await fetchone(
        """
        SELECT COALESCE(SUM(cost_uah), 0) AS total
        FROM transactions
        WHERE chat_id=%s
          AND created_at >= CURDATE()
        """,
        (chat_id,),
    )
    return Decimal(str(row["total"] if row else 0))
