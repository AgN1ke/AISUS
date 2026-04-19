from __future__ import annotations

import pytest

import app.admin_ui as admin_ui
from db import admin_repository


def test_normalize_topup_sort_falls_back_to_safe_defaults():
    sort, direction = admin_repository.normalize_topup_sort("bogus", "sideways")

    assert sort == "created_at"
    assert direction == "desc"


@pytest.mark.asyncio
async def test_list_topups_with_stats_uses_sanitized_filters(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_fetchall(sql, args=None, dict_cursor=True):
        captured["sql"] = sql
        captured["args"] = args
        captured["dict_cursor"] = dict_cursor
        return [{"id": 11}]

    monkeypatch.setattr(admin_repository, "fetchall", fake_fetchall)

    rows = await admin_repository.list_topups_with_stats(
        sort="amount_uah",
        direction="asc",
        query="manual",
        status="manual",
        date_from="2026-04-18",
        date_to="2026-04-19",
        limit=25,
    )

    assert rows == [{"id": 11}]
    assert "ORDER BY t.amount_uah asc" in captured["sql"]
    assert "t.status = %s" in captured["sql"]
    assert "t.created_at < DATE_ADD(%s, INTERVAL 1 DAY)" in captured["sql"]
    assert captured["args"] == (
        "%manual%",
        "%manual%",
        "%manual%",
        "%manual%",
        "%manual%",
        "%manual%",
        "%manual%",
        "%manual%",
        "manual",
        "2026-04-18 00:00:00",
        "2026-04-19",
        25,
    )
    assert captured["dict_cursor"] is True


@pytest.mark.asyncio
async def test_get_topups_summary_reuses_filter_builder(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_fetchone(sql, args=None, dict_cursor=True):
        captured["sql"] = sql
        captured["args"] = args
        return {"total_topups": 3}

    monkeypatch.setattr(admin_repository, "fetchone", fake_fetchone)

    summary = await admin_repository.get_topups_summary(
        query="mike",
        status="success",
    )

    assert summary == {"total_topups": 3}
    assert "COUNT(*) AS total_topups" in captured["sql"]
    assert "t.status = %s" in captured["sql"]
    assert captured["args"] == (
        "%mike%",
        "%mike%",
        "%mike%",
        "%mike%",
        "%mike%",
        "%mike%",
        "%mike%",
        "%mike%",
        "success",
    )


def test_render_admin_topups_page_has_filters_and_user_links():
    html = admin_ui.render_admin_topups_page(
        [
            {
                "id": 11,
                "account_id": 7,
                "amount_uah": "50.00",
                "status": "manual",
                "note": "admin_manual:korol:test topup",
                "created_at": "2026-04-18 18:11:00",
                "paid_at": None,
                "monopay_invoice_id": None,
                "user_id": 42,
                "tg_username": "mike",
                "first_name": "Mike",
            }
        ],
        {
            "total_topups": 1,
            "total_amount_uah": "50.00",
            "success_amount_uah": "0.00",
            "manual_amount_uah": "50.00",
            "pending_count": 0,
        },
        sort="created_at",
        direction="desc",
        query="mike",
        status="manual",
    )

    assert 'action="/admin/topups"' in html
    assert 'href="/admin/users/42"' in html
    assert "admin_manual" in html
    assert "manual" in html
    assert "Поповнення" in html
