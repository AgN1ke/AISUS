from __future__ import annotations

import app.admin_ui as admin_ui


def test_render_dashboard_has_admin_users_link():
    html = admin_ui.render_dashboard(
        {
            "SMARTEST_ADMIN_USERNAME": "korol",
            "SMARTEST_ADMIN_PASSWORD": "secret",
        }
    )

    assert 'href="/admin/users"' in html


def test_render_admin_users_page_has_detail_links_and_filter_form():
    html = admin_ui.render_admin_users_page(
        [
            {
                "user_id": 42,
                "tg_username": "mike",
                "first_name": "Mike",
                "first_seen_at": "2026-04-18 12:00:00",
                "last_seen_at": "2026-04-18 13:00:00",
                "balance_uah": "77.25",
                "total_spent_uah": "10.00",
                "total_topup_uah": "87.25",
                "turns_total": 12,
                "turns_today": 3,
                "turns_7d": 9,
                "tokens_in": 1234,
                "tokens_out": 567,
                "favorite_model": "gpt-5.4-mini",
            }
        ],
        sort="last_seen_at",
        direction="desc",
        query="mike",
    )

    assert 'action="/admin/users"' in html
    assert 'href="/admin/users/42"' in html
    assert "gpt-5.4-mini" in html


def test_render_admin_user_detail_page_has_credit_form_and_settings():
    html = admin_ui.render_admin_user_detail_page(
        {
            "user_id": 42,
            "tg_username": "mike",
            "first_name": "Mike",
            "last_name": "Stone",
            "lang_code": "uk",
            "first_seen_at": "2026-04-18 12:00:00",
            "last_seen_at": "2026-04-18 13:00:00",
            "account_id": 7,
            "balance_uah": "77.25",
            "total_spent_uah": "10.00",
            "total_topup_uah": "87.25",
            "owned_chats_count": 1,
            "turns_total": 12,
            "turns_today": 3,
            "owned_chats": [{"chat_id": -1001, "tg_chat_type": "group", "title": "Test chat"}],
            "recent_turns": [],
            "recent_transactions": [],
            "recent_topups": [],
            "user_settings": {"chat_model": "gpt-5.4-mini"},
        }
    )

    assert 'action="/admin/users/42/credit"' in html
    assert "chat_model" in html
    assert "Test chat" in html


def test_admin_user_path_parsers():
    assert admin_ui._parse_admin_user_detail_path("/admin/users/42") == 42
    assert admin_ui._parse_admin_user_detail_path("/admin/users/42/credit") is None
    assert admin_ui._parse_admin_user_credit_path("/admin/users/42/credit") == 42
    assert admin_ui._parse_admin_user_credit_path("/admin/users/nope") is None

