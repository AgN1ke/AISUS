from __future__ import annotations

from decimal import Decimal

import pytest

from db import admin_repository


def test_normalize_user_sort_falls_back_to_safe_defaults():
    sort, direction = admin_repository.normalize_user_sort("bogus", "sideways")

    assert sort == "last_seen_at"
    assert direction == "desc"


@pytest.mark.asyncio
async def test_list_users_with_stats_uses_sanitized_sort_and_query(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_fetchall(sql, args=None, dict_cursor=True):
        captured["sql"] = sql
        captured["args"] = args
        captured["dict_cursor"] = dict_cursor
        return [{"user_id": 1}]

    monkeypatch.setattr(admin_repository, "fetchall", fake_fetchall)

    rows = await admin_repository.list_users_with_stats(
        sort="balance_uah",
        direction="asc",
        query="mike",
        limit=25,
    )

    assert rows == [{"user_id": 1}]
    assert "ORDER BY a.balance_uah asc" in captured["sql"]
    assert captured["args"] == ("%mike%", "%mike%", "%mike%", "%mike%", 25)
    assert captured["dict_cursor"] is True


@pytest.mark.asyncio
async def test_credit_account_admin_creates_account_when_missing(monkeypatch):
    async def fake_get_user(user_id):
        return {"user_id": user_id, "tg_username": "mike"}

    async def fake_get_account_by_owner(user_id):
        return None

    created = {}

    async def fake_create_account(user_id, initial_balance_uah=0):
        created["account"] = (user_id, initial_balance_uah)
        return 55

    async def fake_create_topup(**kwargs):
        created["topup"] = kwargs
        return 91

    async def fake_credit_account(account_id, amount, count_as_topup=True):
        created["credit"] = (account_id, amount, count_as_topup)
        return Decimal("77.25")

    monkeypatch.setattr(admin_repository, "get_user", fake_get_user)
    monkeypatch.setattr(admin_repository, "get_account_by_owner", fake_get_account_by_owner)
    monkeypatch.setattr(admin_repository, "create_account", fake_create_account)
    monkeypatch.setattr(admin_repository, "create_topup", fake_create_topup)
    monkeypatch.setattr(admin_repository, "credit_account", fake_credit_account)

    result = await admin_repository.credit_account_admin(
        user_id=42,
        amount_uah=Decimal("50"),
        note="manual test",
        actor="korol",
    )

    assert created["account"] == (42, 0)
    assert created["topup"]["account_id"] == 55
    assert created["topup"]["status"] == "manual"
    assert "korol" in created["topup"]["note"]
    assert created["credit"] == (55, Decimal("50"), True)
    assert result["topup_id"] == 91
    assert result["new_balance_uah"] == Decimal("77.25")

