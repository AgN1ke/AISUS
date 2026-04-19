"""Seed the primary owner account.

Creates a user + account for OWNER_TG_USER_ID with a very large balance,
then links every existing chat without an owner to that account.

Usage:
    OWNER_TG_USER_ID=12345678 python scripts/seed_owner_account.py

Env vars:
    OWNER_TG_USER_ID      — Telegram user id (required)
    OWNER_TG_USERNAME     — optional, just for visibility
    OWNER_FIRST_NAME      — optional
    OWNER_SEED_BALANCE    — UAH balance, default 999999
"""
from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.accounts_repository import create_account, get_account_by_owner
from db.bootstrap import bootstrap_db
from db.chats_repository import list_unowned_chats, set_chat_owner
from db.users_repository import get_user, upsert_user


async def main() -> int:
    raw_id = os.getenv("OWNER_TG_USER_ID", "").strip()
    if not raw_id:
        print("ERROR: set OWNER_TG_USER_ID env var")
        return 2
    try:
        owner_id = int(raw_id)
    except ValueError:
        print(f"ERROR: OWNER_TG_USER_ID must be an integer, got {raw_id!r}")
        return 2

    balance = Decimal(os.getenv("OWNER_SEED_BALANCE", "999999"))
    username = os.getenv("OWNER_TG_USERNAME") or None
    first_name = os.getenv("OWNER_FIRST_NAME") or None

    await bootstrap_db()

    await upsert_user(owner_id, tg_username=username, first_name=first_name)
    user = await get_user(owner_id)
    print(f"user: id={user['user_id']} username={user.get('tg_username')!r}")

    account = await get_account_by_owner(owner_id)
    if account:
        account_id = int(account["account_id"])
        print(f"account exists: id={account_id} balance={account['balance_uah']}")
    else:
        account_id = await create_account(owner_id, initial_balance_uah=balance)
        print(f"account created: id={account_id} balance={balance}")

    chats = await list_unowned_chats(limit=1000)
    print(f"unowned chats: {len(chats)}")
    for chat in chats:
        await set_chat_owner(int(chat["chat_id"]), account_id)
        print(f"  linked chat_id={chat['chat_id']} title={chat.get('title')!r}")

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
