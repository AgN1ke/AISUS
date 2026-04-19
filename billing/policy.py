"""Policy and budget checks for the multitenant pipeline.

Two distinct gates per message:

1. **Access** — `chat_policies.access_mode` (open / whitelist / admins_only /
   owner_only) plus per-user `chat_access` rows (banned / allowed /
   delegated_admin). Rejecting here is silent unless the user holds
   delegated_admin or is the chat owner.

2. **Budget** — pre-flight estimate of the message cost vs account balance
   and per-user / per-chat daily caps. Rejecting here sends a polite
   "поповни баланс" or "ліміт вичерпано" message back to the user.

The legacy `chat_join_password` gate (in `app.message_logic.check_access`)
runs before any of this.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from db.accounts_repository import get_account
from db.chats_repository import (
    ensure_chat_policy,
    get_chat,
    get_chat_access,
    get_chat_policy,
    set_chat_owner,
)
from db.transactions_repository import (
    sum_chat_spent_today,
    sum_user_spent_today,
)

logger = logging.getLogger(__name__)


# ── Decision objects ────────────────────────────────────────────────────────


@dataclass
class AccessDecision:
    allowed: bool
    reason: str = ""
    message: str | None = None  # if set, send to user; else silent block


@dataclass
class BudgetDecision:
    allowed: bool
    reason: str = ""
    estimated_uah: Decimal = Decimal("0")
    available_uah: Decimal = Decimal("0")
    message: str | None = None


# ── Owner auto-assignment ───────────────────────────────────────────────────


async def assign_owner_if_unassigned(chat_id: int, account_id: int) -> bool:
    """If the chat has no owner_account_id, set it to this account.

    Returns True when assignment was performed (caller may want to log it).
    """
    chat = await get_chat(int(chat_id))
    if not chat:
        return False
    if chat.get("owner_account_id"):
        return False
    await set_chat_owner(int(chat_id), int(account_id))
    logger.info(
        "policy.owner_assigned chat_id=%s account_id=%s",
        chat_id,
        account_id,
    )
    return True


# ── Access checks ───────────────────────────────────────────────────────────


_NO_OWNER_MESSAGE = (
    "Цей чат ще не активовано. Власник має написати /start у приватному чаті "
    "з ботом і поповнити баланс — після цього чат стане активним."
)


_BANNED_MESSAGE = "Доступ обмежено."

_NOT_WHITELISTED_MESSAGE = (
    "Цей чат працює у режимі whitelist. Доступ для тебе не відкритий."
)


async def check_chat_access(
    *,
    chat_id: int,
    user_id: int,
    account_id: int | None,
) -> AccessDecision:
    """Check chat policy + per-user access rows.

    `account_id` is the resolved billing account for this turn (sender's own
    or chat's owner). If None, billing is impossible.
    """
    chat = await get_chat(int(chat_id))
    owner_account_id = (chat or {}).get("owner_account_id")

    # Per-user rows trump policy.
    access_row = await get_chat_access(int(chat_id), int(user_id))
    if access_row:
        role = access_row.get("role")
        if role == "banned":
            return AccessDecision(
                allowed=False,
                reason="banned",
                message=_BANNED_MESSAGE,
            )
        if role in {"allowed", "delegated_admin"}:
            # Whitelisted users sail through regardless of mode.
            if account_id is None and not owner_account_id:
                return AccessDecision(
                    allowed=False,
                    reason="no_owner",
                    message=_NO_OWNER_MESSAGE,
                )
            return AccessDecision(allowed=True)

    # No explicit row — fall back to policy.
    policy = await get_chat_policy(int(chat_id))
    if not policy:
        # First time we see this chat — initialize a default policy row.
        policy = await ensure_chat_policy(int(chat_id))

    mode = (policy or {}).get("access_mode") or "open"

    if owner_account_id is None and account_id is None:
        return AccessDecision(
            allowed=False,
            reason="no_owner",
            message=_NO_OWNER_MESSAGE,
        )

    if mode == "open":
        return AccessDecision(allowed=True)
    if mode == "owner_only":
        if account_id is not None and owner_account_id == account_id:
            return AccessDecision(allowed=True)
        return AccessDecision(
            allowed=False,
            reason="owner_only",
        )
    if mode == "admins_only":
        # Stage 3 minimal: only chat owner and delegated_admin pass.
        if account_id is not None and owner_account_id == account_id:
            return AccessDecision(allowed=True)
        return AccessDecision(allowed=False, reason="admins_only")
    if mode == "whitelist":
        # Already covered by access_row check above; reaching here means no row.
        return AccessDecision(
            allowed=False,
            reason="not_whitelisted",
            message=_NOT_WHITELISTED_MESSAGE,
        )
    # Unknown mode → fail closed.
    return AccessDecision(allowed=False, reason=f"unknown_mode:{mode}")


# ── Budget / preflight ──────────────────────────────────────────────────────


# Heuristic per-capability output token estimate (approximate).
_CAPABILITY_OUTPUT_ESTIMATE = {
    "chat_final": 800,
    "planner": 80,
    "search_compose": 60,
    "search_eval": 80,
    "search_summary": 600,
    "memory_summary": 200,
    "vision": 400,
    "voice": 100,
}


def estimate_tokens_in(text: str) -> int:
    """Rough input token estimate: chars / 3.5."""
    if not text:
        return 0
    return max(1, int(len(text) / 3.5))


def estimate_tokens_out(capability: str = "chat_final") -> int:
    return _CAPABILITY_OUTPUT_ESTIMATE.get(capability, 600)


async def estimate_message_cost(
    *,
    text: str,
    capability: str = "chat_final",
    provider: str | None = None,
    model: str | None = None,
    safety_factor: Decimal = Decimal("1.2"),
) -> Decimal:
    """Conservative UAH estimate for a single message.

    Without a binding/pricing lookup yet, falls back to a per-capability
    flat estimate. Resolved at Stage 3.x once we wire pricing per-capability.
    """
    from .pricing import compute_cost_uah

    tokens_in = estimate_tokens_in(text)
    tokens_out = estimate_tokens_out(capability)

    if provider and model:
        breakdown = await compute_cost_uah(
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        base = breakdown.cost_uah
    else:
        # Fall back to a rough flat: 0.5 UAH per 1k output tokens at default markup.
        base = Decimal(tokens_out) / Decimal(1000) * Decimal("0.5")

    return (base * safety_factor).quantize(Decimal("0.0001"))


async def check_budget(
    *,
    account_id: int,
    chat_id: int,
    user_id: int,
    estimated_uah: Decimal,
) -> BudgetDecision:
    """Verify balance + daily caps allow this message."""
    account = await get_account(int(account_id))
    if not account:
        return BudgetDecision(
            allowed=False,
            reason="account_missing",
            estimated_uah=estimated_uah,
            message=_NO_OWNER_MESSAGE,
        )
    if account.get("status") != "active":
        return BudgetDecision(
            allowed=False,
            reason=f"account_{account.get('status')}",
            estimated_uah=estimated_uah,
            available_uah=Decimal(str(account.get("balance_uah") or 0)),
            message="Акаунт неактивний.",
        )

    balance = Decimal(str(account.get("balance_uah") or 0))
    if balance < estimated_uah:
        return BudgetDecision(
            allowed=False,
            reason="insufficient_balance",
            estimated_uah=estimated_uah,
            available_uah=balance,
            message=(
                f"Недостатньо коштів: потрібно ≈ {estimated_uah} грн, "
                f"на балансі {balance} грн. Поповни баланс через /topup."
            ),
        )

    policy = await get_chat_policy(int(chat_id))
    if policy:
        per_user_cap = policy.get("per_user_daily_cap_uah")
        if per_user_cap is not None and Decimal(str(per_user_cap)) > 0:
            spent_user = await sum_user_spent_today(int(chat_id), int(user_id))
            if spent_user + estimated_uah > Decimal(str(per_user_cap)):
                return BudgetDecision(
                    allowed=False,
                    reason="user_daily_cap",
                    estimated_uah=estimated_uah,
                    available_uah=balance,
                    message=None,  # silent — спам-блокер
                )
        per_chat_cap = policy.get("per_chat_daily_cap_uah")
        if per_chat_cap is not None and Decimal(str(per_chat_cap)) > 0:
            spent_chat = await sum_chat_spent_today(int(chat_id))
            if spent_chat + estimated_uah > Decimal(str(per_chat_cap)):
                return BudgetDecision(
                    allowed=False,
                    reason="chat_daily_cap",
                    estimated_uah=estimated_uah,
                    available_uah=balance,
                    message=None,
                )

    return BudgetDecision(
        allowed=True,
        estimated_uah=estimated_uah,
        available_uah=balance,
    )
