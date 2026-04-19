"""Per-turn bootstrap: resolve user/account/chat ids and create a Turn row.

Call site is `app/message_logic.py::process_message`. We populate `users`
(via upsert), then look up an `accounts` row owned by the sender. If none
exists, we fall back to the chat owner. If neither resolves, billing is
skipped for this message — the bot still answers, but no transactions are
written. Stage 3 will tighten this with policy enforcement.
"""
from __future__ import annotations

import logging
from typing import Optional

from db.accounts_repository import get_account, get_account_by_owner
from db.chats_repository import ensure_chat, get_chat
from db.transactions_repository import create_turn, finalize_turn
from db.users_repository import get_user_settings, upsert_user

from .context import BillingContext

logger = logging.getLogger(__name__)


async def resolve_account_for(
    *,
    user_id: int | None,
    chat_id: int,
) -> Optional[int]:
    """Find the account that should be billed for a message.

    Order: sender's own account → chat owner_account_id → None.
    """
    if user_id:
        own = await get_account_by_owner(int(user_id))
        if own:
            return int(own["account_id"])
    chat_row = await get_chat(int(chat_id))
    if chat_row and chat_row.get("owner_account_id"):
        owner_account_id = int(chat_row["owner_account_id"])
        owner_acct = await get_account(owner_account_id)
        if owner_acct and owner_acct.get("status") == "active":
            return owner_account_id
    return None


async def begin_turn(
    *,
    chat_id: int,
    user_id: int | None,
    tg_chat_type: str | None = None,
    tg_username: str | None = None,
    first_name: str | None = None,
    tg_message_id: int | None = None,
    user_message_text: str | None = None,
) -> Optional[BillingContext]:
    """Ensure user/chat exist, resolve account, create a turn, return context.

    Returns None if no account can be attributed (no billing for this turn).
    """
    if not user_id or int(user_id) <= 0:
        return None

    try:
        await upsert_user(
            int(user_id),
            tg_username=tg_username,
            first_name=first_name,
        )
    except Exception as exc:
        logger.warning("billing.bootstrap.upsert_user failed user_id=%s: %s", user_id, exc)

    try:
        await ensure_chat(int(chat_id), tg_chat_type=tg_chat_type)
    except Exception as exc:
        logger.warning("billing.bootstrap.ensure_chat failed chat_id=%s: %s", chat_id, exc)

    account_id = await resolve_account_for(user_id=user_id, chat_id=chat_id)
    if account_id is None:
        logger.info(
            "billing.bootstrap.no_account chat_id=%s user_id=%s — billing skipped",
            chat_id,
            user_id,
        )
        return None

    try:
        turn_id = await create_turn(
            account_id=account_id,
            chat_id=int(chat_id),
            user_id=int(user_id),
            tg_message_id=tg_message_id,
            user_message_text=user_message_text,
        )
    except Exception as exc:
        logger.warning("billing.bootstrap.create_turn failed: %s", exc)
        return None

    user_settings: dict[str, str] = {}
    try:
        user_settings = await get_user_settings(int(user_id))
    except Exception as exc:
        logger.warning(
            "billing.bootstrap.get_user_settings failed user_id=%s: %s",
            user_id,
            exc,
        )

    return BillingContext(
        turn_id=turn_id,
        account_id=account_id,
        chat_id=int(chat_id),
        user_id=int(user_id),
        meta={"user_settings": user_settings},
    )


async def end_turn(
    ctx: Optional[BillingContext],
    *,
    status: str = "completed",
    route: str | None = None,
    capability: str | None = None,
) -> None:
    if ctx is None or not ctx.turn_id:
        return
    try:
        await finalize_turn(
            ctx.turn_id,
            status=status,
            route=route,
            capability=capability,
        )
    except Exception as exc:
        logger.warning("billing.bootstrap.finalize_turn failed turn=%s: %s", ctx.turn_id, exc)
