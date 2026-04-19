from __future__ import annotations

import pytest

import app.admin_ui as admin_ui
from billing.crypto import encrypt_key
from db import admin_repository


def test_normalize_key_sort_falls_back_to_safe_defaults():
    sort, direction = admin_repository.normalize_key_sort("bogus", "sideways")

    assert sort == "provider"
    assert direction == "desc"


@pytest.mark.asyncio
async def test_list_provider_keys_with_stats_uses_sanitized_filters(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_fetchall(sql, args=None, dict_cursor=True):
        captured["sql"] = sql
        captured["args"] = args
        captured["dict_cursor"] = dict_cursor
        return [{"id": 17}]

    monkeypatch.setattr(admin_repository, "fetchall", fake_fetchall)

    rows = await admin_repository.list_provider_keys_with_stats(
        sort="total_spent_usd",
        direction="asc",
        query="openai-main",
        provider="openai",
        status="active",
        limit=25,
    )

    assert rows == [{"id": 17}]
    assert "ORDER BY pk.total_spent_usd asc" in captured["sql"]
    assert "pk.provider = %s" in captured["sql"]
    assert "pk.status = %s" in captured["sql"]
    assert captured["args"] == (
        "%openai-main%",
        "%openai-main%",
        "%openai-main%",
        "%openai-main%",
        "%openai-main%",
        "openai",
        "active",
        25,
    )
    assert captured["dict_cursor"] is True


@pytest.mark.asyncio
async def test_get_provider_keys_summary_reuses_filter_builder(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_fetchone(sql, args=None, dict_cursor=True):
        captured["sql"] = sql
        captured["args"] = args
        return {"total_keys": 2}

    monkeypatch.setattr(admin_repository, "fetchone", fake_fetchone)

    summary = await admin_repository.get_provider_keys_summary(
        query="AIza",
        status="invalid",
    )

    assert summary == {"total_keys": 2}
    assert "COUNT(*) AS total_keys" in captured["sql"]
    assert "pk.status = %s" in captured["sql"]
    assert captured["args"] == (
        "%AIza%",
        "%AIza%",
        "%AIza%",
        "%AIza%",
        "%AIza%",
        "invalid",
    )


def test_render_admin_keys_page_has_add_form_toggle_and_masked_key():
    encrypted = encrypt_key("sk-test-secret-1234")
    html = admin_ui.render_admin_keys_page(
        [
            {
                "id": 17,
                "provider": "openai",
                "label": "openai-main-1",
                "key_hash": "abcdef1234567890fedcba0987654321abcdef1234567890fedcba0987654321",
                "encrypted_key": encrypted,
                "status": "active",
                "rpm_limit": 60,
                "tpm_limit": 100000,
                "total_requests": 33,
                "total_spent_usd": "1.234567",
                "last_used_at": "2026-04-18 18:45:00",
                "last_error_at": None,
                "last_error": "",
                "cooldown_until": None,
                "created_at": "2026-04-18 17:00:00",
            }
        ],
        {
            "total_keys": 1,
            "active_keys": 1,
            "disabled_keys": 0,
            "rate_limited_keys": 0,
            "invalid_keys": 0,
            "total_requests": 33,
            "total_spent_usd": "1.234567",
        },
        sort="provider",
        direction="asc",
        provider="openai",
    )

    assert 'action="/admin/keys/add"' in html
    assert 'action="/admin/keys/17/toggle"' in html
    assert "openai-main-1" in html
    assert "Disable" in html
    assert "abcdef12" in html
    assert "1234" in html
    assert "sk-test-secret-1234" not in html


def test_admin_key_toggle_path_parser():
    assert admin_ui._parse_admin_key_toggle_path("/admin/keys/17/toggle") == 17
    assert admin_ui._parse_admin_key_toggle_path("/admin/keys/17") is None
