from __future__ import annotations

import pytest

import app.admin_ui as admin_ui
from db import admin_repository


def test_normalize_chat_sort_falls_back_to_safe_defaults():
    sort, direction = admin_repository.normalize_chat_sort("bogus", "sideways")

    assert sort == "last_turn_at"
    assert direction == "desc"


@pytest.mark.asyncio
async def test_list_chats_with_stats_uses_sanitized_filters(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_fetchall(sql, args=None, dict_cursor=True):
        captured["sql"] = sql
        captured["args"] = args
        captured["dict_cursor"] = dict_cursor
        return [{"chat_id": -1001}]

    monkeypatch.setattr(admin_repository, "fetchall", fake_fetchall)

    rows = await admin_repository.list_chats_with_stats(
        sort="spent_total_uah",
        direction="asc",
        query="research",
        access_mode="whitelist",
        tg_chat_type="group",
        limit=25,
    )

    assert rows == [{"chat_id": -1001}]
    assert "ORDER BY spent_total_uah asc" in captured["sql"]
    assert "cp.access_mode = %s" in captured["sql"]
    assert "c.tg_chat_type = %s" in captured["sql"]
    assert captured["args"] == (
        "%research%",
        "%research%",
        "%research%",
        "%research%",
        "%research%",
        "whitelist",
        "group",
        25,
    )
    assert captured["dict_cursor"] is True


@pytest.mark.asyncio
async def test_get_chats_summary_reuses_filter_builder(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_fetchone(sql, args=None, dict_cursor=True):
        captured["sql"] = sql
        captured["args"] = args
        return {"total_chats": 4}

    monkeypatch.setattr(admin_repository, "fetchone", fake_fetchone)

    summary = await admin_repository.get_chats_summary(
        query="mike",
        tg_chat_type="supergroup",
    )

    assert summary == {"total_chats": 4}
    assert "COUNT(*) AS total_chats" in captured["sql"]
    assert "c.tg_chat_type = %s" in captured["sql"]
    assert captured["args"] == (
        "%mike%",
        "%mike%",
        "%mike%",
        "%mike%",
        "%mike%",
        "supergroup",
    )


def test_render_admin_chats_page_has_filters_and_owner_links():
    html = admin_ui.render_admin_chats_page(
        [
            {
                "chat_id": -1001,
                "title": "Research Guild",
                "tg_chat_type": "group",
                "owner_user_id": 42,
                "owner_label": "@mike · Mike Stone",
                "access_mode": "whitelist",
                "per_user_daily_cap_uah": "5.0000",
                "per_chat_daily_cap_uah": "50.0000",
                "spent_today_uah": "1.2500",
                "spent_total_uah": "15.5000",
                "last_turn_at": "2026-04-18 17:42:00",
                "allowed_count": 3,
                "delegated_admin_count": 1,
                "banned_count": 2,
            }
        ],
        {
            "total_chats": 1,
            "owned_chats": 1,
            "restricted_chats": 1,
            "total_spent_today_uah": "1.2500",
            "total_spent_uah": "15.5000",
        },
        sort="last_turn_at",
        direction="desc",
        query="research",
        access_mode="whitelist",
        tg_chat_type="group",
    )

    assert 'action="/admin/chats"' in html
    assert 'href="/admin/users/42"' in html
    assert "Research Guild" in html
    assert "whitelist" in html
    assert "Spent today" in html
