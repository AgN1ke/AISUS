from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .connection import execute, fetchall, fetchone, get_conn_cursor


class InsufficientBalanceError(Exception):
    """Raised when debit would drive balance below zero."""


async def create_account(
    owner_user_id: int,
    initial_balance_uah: Decimal | float | int = 0,
) -> int:
    """Create a new account for a user. Returns account_id."""
    async with get_conn_cursor() as (conn, cur):
        await cur.execute(
            """
            INSERT INTO accounts (owner_user_id, balance_uah, total_topup_uah)
            VALUES (%s, %s, %s)
            """,
            (owner_user_id, Decimal(str(initial_balance_uah)), Decimal(str(initial_balance_uah))),
        )
        account_id = cur.lastrowid
        await conn.commit()
        return int(account_id)


async def get_account(account_id: int) -> Optional[dict]:
    return await fetchone(
        "SELECT * FROM accounts WHERE account_id=%s",
        (account_id,),
    )


async def get_account_by_owner(owner_user_id: int) -> Optional[dict]:
    """Fetch the primary (first active) account for a user."""
    return await fetchone(
        """
        SELECT * FROM accounts
        WHERE owner_user_id=%s AND status='active'
        ORDER BY account_id ASC LIMIT 1
        """,
        (owner_user_id,),
    )


async def list_accounts(limit: int = 100) -> list[dict]:
    return await fetchall(
        "SELECT * FROM accounts ORDER BY account_id ASC LIMIT %s",
        (limit,),
    ) or []


async def debit_account(
    account_id: int,
    amount_uah: Decimal | float | int,
) -> Decimal:
    """Atomically subtract amount from balance. Returns new balance.

    Raises InsufficientBalanceError if balance would go negative.
    """
    amount = Decimal(str(amount_uah))
    if amount < 0:
        raise ValueError("amount_uah must be non-negative")

    async with get_conn_cursor(dict_cursor=True) as (conn, cur):
        try:
            await conn.begin()
            await cur.execute(
                "SELECT balance_uah, status FROM accounts WHERE account_id=%s FOR UPDATE",
                (account_id,),
            )
            row = await cur.fetchone()
            if not row:
                await conn.rollback()
                raise ValueError(f"Account {account_id} not found")
            if row["status"] != "active":
                await conn.rollback()
                raise InsufficientBalanceError(f"Account {account_id} is {row['status']}")
            current = Decimal(str(row["balance_uah"]))
            if current < amount:
                await conn.rollback()
                raise InsufficientBalanceError(
                    f"Balance {current} < required {amount}"
                )
            new_balance = current - amount
            await cur.execute(
                """
                UPDATE accounts
                SET balance_uah = %s,
                    total_spent_uah = total_spent_uah + %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE account_id = %s
                """,
                (new_balance, amount, account_id),
            )
            await conn.commit()
            return new_balance
        except Exception:
            try:
                await conn.rollback()
            except Exception:
                pass
            raise


async def credit_account(
    account_id: int,
    amount_uah: Decimal | float | int,
    *,
    count_as_topup: bool = True,
) -> Decimal:
    """Atomically add amount to balance. Returns new balance."""
    amount = Decimal(str(amount_uah))
    if amount < 0:
        raise ValueError("amount_uah must be non-negative")

    async with get_conn_cursor(dict_cursor=True) as (conn, cur):
        try:
            await conn.begin()
            await cur.execute(
                "SELECT balance_uah FROM accounts WHERE account_id=%s FOR UPDATE",
                (account_id,),
            )
            row = await cur.fetchone()
            if not row:
                await conn.rollback()
                raise ValueError(f"Account {account_id} not found")
            current = Decimal(str(row["balance_uah"]))
            new_balance = current + amount
            if count_as_topup:
                await cur.execute(
                    """
                    UPDATE accounts
                    SET balance_uah = %s,
                        total_topup_uah = total_topup_uah + %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE account_id = %s
                    """,
                    (new_balance, amount, account_id),
                )
            else:
                await cur.execute(
                    """
                    UPDATE accounts
                    SET balance_uah = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE account_id = %s
                    """,
                    (new_balance, account_id),
                )
            await conn.commit()
            return new_balance
        except Exception:
            try:
                await conn.rollback()
            except Exception:
                pass
            raise


async def set_account_status(account_id: int, status: str) -> None:
    if status not in {"active", "frozen", "deleted"}:
        raise ValueError(f"invalid status: {status}")
    await execute(
        "UPDATE accounts SET status=%s, updated_at=CURRENT_TIMESTAMP WHERE account_id=%s",
        (status, account_id),
    )
