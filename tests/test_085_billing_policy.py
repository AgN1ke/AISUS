"""Tests for billing.policy — access + budget gates.

All DB calls are monkeypatched so these run hermetically.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

import billing.policy as policy
from billing.pricing import CostBreakdown


# ── estimate helpers ────────────────────────────────────────────────────────


def test_estimate_tokens_in_empty_returns_zero():
    assert policy.estimate_tokens_in("") == 0
    assert policy.estimate_tokens_in(None) == 0  # type: ignore[arg-type]


def test_estimate_tokens_in_nonempty_is_positive():
    # "hello world" is 11 chars → 11/3.5 ≈ 3 tokens, clamped to min 1.
    assert policy.estimate_tokens_in("hello world") >= 1


def test_estimate_tokens_out_uses_capability_table():
    assert policy.estimate_tokens_out("chat_final") == 800
    assert policy.estimate_tokens_out("planner") == 80
    assert policy.estimate_tokens_out("search_compose") == 60


def test_estimate_tokens_out_unknown_capability_falls_back():
    # Unknown capability → default 600.
    assert policy.estimate_tokens_out("something_new") == 600


@pytest.mark.asyncio
async def test_estimate_message_cost_with_provider_model(monkeypatch):
    async def fake_compute(**kwargs):
        assert kwargs["provider"] == "openai"
        assert kwargs["model"] == "gpt-5.4-mini"
        assert kwargs["tokens_in"] >= 1
        assert kwargs["tokens_out"] == 80
        return CostBreakdown(
            cost_usd=Decimal("0.001"),
            cost_uah=Decimal("0.10"),
            markup_pct=Decimal("40"),
            uah_per_usd=Decimal("40"),
            source="pricing_table",
        )

    monkeypatch.setattr("billing.pricing.compute_cost_uah", fake_compute)

    estimated = await policy.estimate_message_cost(
        text="hello world",
        capability="planner",
        provider="openai",
        model="gpt-5.4-mini",
    )
    # 0.10 UAH * 1.2 safety factor = 0.12 UAH.
    assert estimated == Decimal("0.1200")


@pytest.mark.asyncio
async def test_estimate_message_cost_fallback_when_no_binding():
    # Without provider/model, uses flat 0.5 UAH / 1k output tokens * safety.
    estimated = await policy.estimate_message_cost(
        text="hi",
        capability="planner",  # tokens_out = 80
    )
    # 80/1000 * 0.5 * 1.2 = 0.048
    assert estimated == Decimal("0.0480")


# ── assign_owner_if_unassigned ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_owner_missing_chat(monkeypatch):
    async def fake_get_chat(cid):
        return None

    async def fake_set_owner(cid, aid):
        raise AssertionError("must not be called")

    monkeypatch.setattr("billing.policy.get_chat", fake_get_chat)
    monkeypatch.setattr("billing.policy.set_chat_owner", fake_set_owner)

    assert await policy.assign_owner_if_unassigned(100, 7) is False


@pytest.mark.asyncio
async def test_assign_owner_already_assigned(monkeypatch):
    async def fake_get_chat(cid):
        return {"chat_id": cid, "owner_account_id": 3}

    called = []

    async def fake_set_owner(cid, aid):
        called.append((cid, aid))

    monkeypatch.setattr("billing.policy.get_chat", fake_get_chat)
    monkeypatch.setattr("billing.policy.set_chat_owner", fake_set_owner)

    assert await policy.assign_owner_if_unassigned(100, 7) is False
    assert called == []


@pytest.mark.asyncio
async def test_assign_owner_fills_unassigned(monkeypatch):
    async def fake_get_chat(cid):
        return {"chat_id": cid, "owner_account_id": None}

    called = []

    async def fake_set_owner(cid, aid):
        called.append((cid, aid))

    monkeypatch.setattr("billing.policy.get_chat", fake_get_chat)
    monkeypatch.setattr("billing.policy.set_chat_owner", fake_set_owner)

    assert await policy.assign_owner_if_unassigned(100, 7) is True
    assert called == [(100, 7)]


# ── check_chat_access ──────────────────────────────────────────────────────


def _stub_access_helpers(
    monkeypatch,
    *,
    chat=None,
    access_row=None,
    policy_row=None,
):
    async def fake_get_chat(cid):
        return chat

    async def fake_get_chat_access(cid, uid):
        return access_row

    async def fake_get_chat_policy(cid):
        return policy_row

    async def fake_ensure_chat_policy(cid):
        return {"chat_id": cid, "access_mode": "open"}

    monkeypatch.setattr("billing.policy.get_chat", fake_get_chat)
    monkeypatch.setattr("billing.policy.get_chat_access", fake_get_chat_access)
    monkeypatch.setattr("billing.policy.get_chat_policy", fake_get_chat_policy)
    monkeypatch.setattr(
        "billing.policy.ensure_chat_policy", fake_ensure_chat_policy
    )


@pytest.mark.asyncio
async def test_access_open_mode_allows(monkeypatch):
    _stub_access_helpers(
        monkeypatch,
        chat={"chat_id": 1, "owner_account_id": 1},
        policy_row={"access_mode": "open"},
    )
    decision = await policy.check_chat_access(chat_id=1, user_id=5, account_id=9)
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_access_banned_user_is_blocked_with_message(monkeypatch):
    _stub_access_helpers(
        monkeypatch,
        chat={"chat_id": 1, "owner_account_id": 1},
        access_row={"role": "banned"},
    )
    decision = await policy.check_chat_access(chat_id=1, user_id=5, account_id=9)
    assert decision.allowed is False
    assert decision.reason == "banned"
    assert decision.message


@pytest.mark.asyncio
async def test_access_whitelisted_row_bypasses_mode(monkeypatch):
    _stub_access_helpers(
        monkeypatch,
        chat={"chat_id": 1, "owner_account_id": 1},
        access_row={"role": "allowed"},
        policy_row={"access_mode": "whitelist"},
    )
    decision = await policy.check_chat_access(chat_id=1, user_id=5, account_id=9)
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_access_whitelist_mode_without_row_blocks_with_message(monkeypatch):
    _stub_access_helpers(
        monkeypatch,
        chat={"chat_id": 1, "owner_account_id": 1},
        policy_row={"access_mode": "whitelist"},
    )
    decision = await policy.check_chat_access(chat_id=1, user_id=5, account_id=9)
    assert decision.allowed is False
    assert decision.reason == "not_whitelisted"
    assert decision.message


@pytest.mark.asyncio
async def test_access_owner_only_allows_owner(monkeypatch):
    _stub_access_helpers(
        monkeypatch,
        chat={"chat_id": 1, "owner_account_id": 42},
        policy_row={"access_mode": "owner_only"},
    )
    decision = await policy.check_chat_access(chat_id=1, user_id=5, account_id=42)
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_access_owner_only_silently_blocks_non_owner(monkeypatch):
    _stub_access_helpers(
        monkeypatch,
        chat={"chat_id": 1, "owner_account_id": 42},
        policy_row={"access_mode": "owner_only"},
    )
    decision = await policy.check_chat_access(chat_id=1, user_id=5, account_id=7)
    assert decision.allowed is False
    assert decision.reason == "owner_only"
    assert decision.message is None  # silent


@pytest.mark.asyncio
async def test_access_admins_only_silently_blocks_non_owner(monkeypatch):
    _stub_access_helpers(
        monkeypatch,
        chat={"chat_id": 1, "owner_account_id": 42},
        policy_row={"access_mode": "admins_only"},
    )
    decision = await policy.check_chat_access(chat_id=1, user_id=5, account_id=7)
    assert decision.allowed is False
    assert decision.reason == "admins_only"
    assert decision.message is None


@pytest.mark.asyncio
async def test_access_no_owner_and_no_account_is_blocked_with_prompt(monkeypatch):
    _stub_access_helpers(
        monkeypatch,
        chat={"chat_id": 1, "owner_account_id": None},
        policy_row={"access_mode": "open"},
    )
    decision = await policy.check_chat_access(chat_id=1, user_id=5, account_id=None)
    assert decision.allowed is False
    assert decision.reason == "no_owner"
    assert decision.message


# ── check_budget ───────────────────────────────────────────────────────────


def _stub_budget_helpers(
    monkeypatch,
    *,
    account=None,
    chat_policy=None,
    user_spent=Decimal("0"),
    chat_spent=Decimal("0"),
):
    async def fake_get_account(aid):
        return account

    async def fake_get_chat_policy(cid):
        return chat_policy

    async def fake_sum_user(cid, uid):
        return user_spent

    async def fake_sum_chat(cid):
        return chat_spent

    monkeypatch.setattr("billing.policy.get_account", fake_get_account)
    monkeypatch.setattr("billing.policy.get_chat_policy", fake_get_chat_policy)
    monkeypatch.setattr("billing.policy.sum_user_spent_today", fake_sum_user)
    monkeypatch.setattr("billing.policy.sum_chat_spent_today", fake_sum_chat)


@pytest.mark.asyncio
async def test_budget_account_missing(monkeypatch):
    _stub_budget_helpers(monkeypatch, account=None)
    decision = await policy.check_budget(
        account_id=1, chat_id=2, user_id=3, estimated_uah=Decimal("1")
    )
    assert decision.allowed is False
    assert decision.reason == "account_missing"


@pytest.mark.asyncio
async def test_budget_account_frozen(monkeypatch):
    _stub_budget_helpers(
        monkeypatch,
        account={"status": "frozen", "balance_uah": Decimal("100")},
    )
    decision = await policy.check_budget(
        account_id=1, chat_id=2, user_id=3, estimated_uah=Decimal("1")
    )
    assert decision.allowed is False
    assert decision.reason == "account_frozen"
    assert decision.message


@pytest.mark.asyncio
async def test_budget_insufficient_balance_shows_message(monkeypatch):
    _stub_budget_helpers(
        monkeypatch,
        account={"status": "active", "balance_uah": Decimal("0.10")},
    )
    decision = await policy.check_budget(
        account_id=1, chat_id=2, user_id=3, estimated_uah=Decimal("1")
    )
    assert decision.allowed is False
    assert decision.reason == "insufficient_balance"
    assert decision.message


@pytest.mark.asyncio
async def test_budget_per_user_daily_cap_silently_blocks(monkeypatch):
    _stub_budget_helpers(
        monkeypatch,
        account={"status": "active", "balance_uah": Decimal("100")},
        chat_policy={
            "per_user_daily_cap_uah": Decimal("5"),
            "per_chat_daily_cap_uah": Decimal("0"),
        },
        user_spent=Decimal("4.5"),
    )
    decision = await policy.check_budget(
        account_id=1, chat_id=2, user_id=3, estimated_uah=Decimal("1")
    )
    assert decision.allowed is False
    assert decision.reason == "user_daily_cap"
    assert decision.message is None  # silent anti-spam block


@pytest.mark.asyncio
async def test_budget_per_chat_daily_cap_silently_blocks(monkeypatch):
    _stub_budget_helpers(
        monkeypatch,
        account={"status": "active", "balance_uah": Decimal("100")},
        chat_policy={
            "per_user_daily_cap_uah": Decimal("0"),
            "per_chat_daily_cap_uah": Decimal("10"),
        },
        chat_spent=Decimal("9.5"),
    )
    decision = await policy.check_budget(
        account_id=1, chat_id=2, user_id=3, estimated_uah=Decimal("1")
    )
    assert decision.allowed is False
    assert decision.reason == "chat_daily_cap"
    assert decision.message is None


@pytest.mark.asyncio
async def test_budget_allows_within_limits(monkeypatch):
    _stub_budget_helpers(
        monkeypatch,
        account={"status": "active", "balance_uah": Decimal("100")},
        chat_policy={
            "per_user_daily_cap_uah": Decimal("50"),
            "per_chat_daily_cap_uah": Decimal("200"),
        },
        user_spent=Decimal("5"),
        chat_spent=Decimal("20"),
    )
    decision = await policy.check_budget(
        account_id=1, chat_id=2, user_id=3, estimated_uah=Decimal("1")
    )
    assert decision.allowed is True
    assert decision.available_uah == Decimal("100")
