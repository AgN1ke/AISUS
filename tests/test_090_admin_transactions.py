from __future__ import annotations

import pytest

import app.admin_ui as admin_ui
from db import admin_repository


def test_normalize_transaction_sort_falls_back_to_safe_defaults():
    sort, direction = admin_repository.normalize_transaction_sort("bogus", "sideways")

    assert sort == "created_at"
    assert direction == "desc"


@pytest.mark.asyncio
async def test_list_transactions_with_stats_uses_sanitized_filters(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_fetchall(sql, args=None, dict_cursor=True):
        captured["sql"] = sql
        captured["args"] = args
        captured["dict_cursor"] = dict_cursor
        return [{"id": 1}]

    monkeypatch.setattr(admin_repository, "fetchall", fake_fetchall)

    rows = await admin_repository.list_transactions_with_stats(
        sort="cost_uah",
        direction="asc",
        query="mike",
        capability="chat_final",
        provider="gemini",
        model="gemini-2.5-pro",
        status="success",
        kind="llm_call",
        date_from="2026-04-18",
        date_to="2026-04-19",
        limit=25,
    )

    assert rows == [{"id": 1}]
    assert "ORDER BY tx.cost_uah asc" in captured["sql"]
    assert "tx.capability = %s" in captured["sql"]
    assert "tx.created_at < DATE_ADD(%s, INTERVAL 1 DAY)" in captured["sql"]
    assert captured["args"] == (
        "%mike%", "%mike%", "%mike%", "%mike%", "%mike%",
        "%mike%", "%mike%", "%mike%", "%mike%", "%mike%",
        "chat_final",
        "gemini",
        "gemini-2.5-pro",
        "success",
        "llm_call",
        "2026-04-18 00:00:00",
        "2026-04-19",
        25,
    )
    assert captured["dict_cursor"] is True


@pytest.mark.asyncio
async def test_get_transactions_summary_reuses_filter_builder(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_fetchone(sql, args=None, dict_cursor=True):
        captured["sql"] = sql
        captured["args"] = args
        return {"total_rows": 7}

    monkeypatch.setattr(admin_repository, "fetchone", fake_fetchone)

    summary = await admin_repository.get_transactions_summary(
        query="42",
        provider="openai",
        date_from="2026-04-10",
    )

    assert summary == {"total_rows": 7}
    assert "COUNT(*) AS total_rows" in captured["sql"]
    assert "tx.provider = %s" in captured["sql"]
    assert captured["args"] == (
        "%42%", "%42%", "%42%", "%42%", "%42%",
        "%42%", "%42%", "%42%", "%42%", "%42%",
        "openai",
        "2026-04-10 00:00:00",
    )


def test_render_admin_transactions_page_has_filters_and_user_links():
    html = admin_ui.render_admin_transactions_page(
        [
            {
                "id": 101,
                "turn_id": "turn-1",
                "user_id": 42,
                "tg_username": "mike",
                "first_name": "Mike",
                "chat_id": -1001,
                "chat_title": "Research",
                "tg_chat_type": "group",
                "capability": "chat_final",
                "provider": "gemini",
                "model": "gemini-2.5-pro",
                "status": "success",
                "tokens_in": 1200,
                "tokens_out": 340,
                "unit_count": 0,
                "cost_uah": "0.3142",
                "latency_ms": 1870,
                "error_text": "",
                "created_at": "2026-04-18 14:33:21",
            }
        ],
        {
            "total_rows": 1,
            "total_cost_uah": "0.3142",
            "total_tokens_in": 1200,
            "total_tokens_out": 340,
            "success_count": 1,
            "failed_count": 0,
            "rate_limited_count": 0,
            "avg_latency_ms": 1870,
        },
        sort="created_at",
        direction="desc",
        query="mike",
        provider="gemini",
    )

    assert 'action="/admin/transactions"' in html
    assert 'href="/admin/users/42"' in html
    assert "gemini-2.5-pro" in html
    assert "Глобальний лог транзакцій" in html
    assert "Research" in html
