"""Tests for billing.commands — parser + handler dispatch.

DB calls are monkeypatched to keep these hermetic.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import billing.commands as commands
from adapters.base import MessageGeometry, MessageParticipant, UnifiedMessage


# ── parse_command ──────────────────────────────────────────────────────────


def test_parse_bare_command_private():
    assert commands.parse_command("/start", bot_username="smartest_bot") == ("/start", "")


def test_parse_command_with_args():
    assert commands.parse_command("/topup 100", "smartest_bot") == (
        "/topup",
        "100",
    )


def test_parse_command_with_botname_suffix():
    assert commands.parse_command("/balance@smartest_bot", "smartest_bot") == (
        "/balance",
        "",
    )


def test_parse_command_with_wrong_botname_returns_none():
    assert commands.parse_command("/start@otherbot", "smartest_bot") is None


def test_parse_non_command_returns_none():
    assert commands.parse_command("hello there", "smartest_bot") is None
    assert commands.parse_command("", "smartest_bot") is None
    assert commands.parse_command(None, "smartest_bot") is None  # type: ignore[arg-type]


def test_parse_unknown_command_returns_none():
    assert commands.parse_command("/unknowncmd", "smartest_bot") is None


# ── _parse_amount ──────────────────────────────────────────────────────────


def test_parse_amount_handles_decimal_and_comma():
    assert commands._parse_amount("50") == Decimal("50.00")
    assert commands._parse_amount("50.5") == Decimal("50.50")
    assert commands._parse_amount("50,5") == Decimal("50.50")


def test_parse_amount_rejects_invalid():
    assert commands._parse_amount("") is None
    assert commands._parse_amount("abc") is None
    assert commands._parse_amount("-10") is None
    assert commands._parse_amount("0") is None


# ── Helpers for building msg/geometry fixtures ─────────────────────────────


def _msg(text: str, *, chat_id: int = 100, bot_username: str = "smartest_bot"):
    return UnifiedMessage(
        platform="ptb",
        chat_id=chat_id,
        message_id=1,
        text=text,
        caption=None,
        reply_to_message_id=None,
        has_photo=False,
        has_voice=False,
        has_video=False,
        has_document=False,
        raw_update=None,
        bot_username=bot_username,
    )


def _geo(*, user_id: int = 42, chat_type: str = "private", username: str | None = None):
    return MessageGeometry(
        chat_type=chat_type,
        sender=MessageParticipant(user_id=user_id, username=username, display_name="Test"),
    )


# ── /start ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_in_group_redirects_to_private(monkeypatch):
    result = await commands._cmd_start(
        msg=_msg("/start"),
        geometry=_geo(chat_type="group"),
        args="",
        billing_ctx=None,
    )
    assert result.handled is True
    assert "приватному" in (result.response_text or "")


@pytest.mark.asyncio
async def test_start_creates_account_when_none(monkeypatch):
    async def fake_upsert_user(*a, **kw):
        return None

    async def fake_get_account_by_owner(uid):
        return None

    created_calls: list = []

    async def fake_create_account(uid, initial_balance_uah=0):
        created_calls.append((uid, initial_balance_uah))
        return 777

    async def fake_get_account(aid):
        return {"account_id": aid, "balance_uah": Decimal("0")}

    monkeypatch.setattr("billing.commands.upsert_user", fake_upsert_user)
    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    monkeypatch.setattr("billing.commands.create_account", fake_create_account)
    monkeypatch.setattr("billing.commands.get_account", fake_get_account)

    result = await commands._cmd_start(
        msg=_msg("/start"),
        geometry=_geo(user_id=42),
        args="",
        billing_ctx=None,
    )
    assert result.handled is True
    assert created_calls == [(42, 0)]
    assert "створив" in (result.response_text or "").lower()


@pytest.mark.asyncio
async def test_start_shows_balance_when_account_exists(monkeypatch):
    async def fake_upsert_user(*a, **kw):
        return None

    async def fake_get_account_by_owner(uid):
        return {"account_id": 1, "balance_uah": Decimal("75")}

    monkeypatch.setattr("billing.commands.upsert_user", fake_upsert_user)
    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)

    result = await commands._cmd_start(
        msg=_msg("/start"),
        geometry=_geo(user_id=42),
        args="",
        billing_ctx=None,
    )
    assert "75.00" in (result.response_text or "")


# ── /balance ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_balance_no_account(monkeypatch):
    async def fake_get_account_by_owner(uid):
        return None

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    result = await commands._cmd_balance(
        msg=_msg("/balance"),
        geometry=_geo(user_id=42),
        args="",
        billing_ctx=None,
    )
    assert "/start" in (result.response_text or "")


@pytest.mark.asyncio
async def test_balance_with_account_and_turns(monkeypatch):
    async def fake_get_account_by_owner(uid):
        return {
            "account_id": 1,
            "balance_uah": Decimal("42.50"),
            "total_spent_uah": Decimal("8"),
            "total_topup_uah": Decimal("50"),
        }

    async def fake_sum_chat_today(cid):
        return Decimal("1.25")

    async def fake_list_turns(aid, limit=5):
        return [
            {"capability": "chat_final", "total_cost_uah": Decimal("0.08"), "status": "completed"},
            {"capability": "planner", "total_cost_uah": Decimal("0.005"), "status": "completed"},
        ]

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    monkeypatch.setattr("billing.commands.sum_chat_spent_today", fake_sum_chat_today)
    monkeypatch.setattr("billing.commands.list_turns_for_account", fake_list_turns)

    result = await commands._cmd_balance(
        msg=_msg("/balance"),
        geometry=_geo(user_id=42, chat_type="group"),
        args="",
        billing_ctx=None,
    )
    text = result.response_text or ""
    assert "42.50" in text
    assert "chat_final" in text
    assert "1.25" in text  # chat-today line appears in non-private
    assert "/balance last" in text
    assert "/balance turn" in text


@pytest.mark.asyncio
async def test_balance_last_renders_subtransaction_breakdown(monkeypatch):
    async def fake_get_account_by_owner(uid):
        return {
            "account_id": 1,
            "balance_uah": Decimal("42.50"),
            "total_spent_uah": Decimal("8"),
            "total_topup_uah": Decimal("50"),
        }

    async def fake_get_latest_turn(account_id):
        return {
            "turn_id": "abcd1234-0000-0000-0000-000000000000",
            "total_cost_uah": Decimal("0.18"),
            "status": "completed",
            "route": "chat",
            "capability": "chat_final",
            "user_message_text": "Explain cotton domestication",
        }

    async def fake_get_transactions_for_turn(turn_id):
        return [
            {
                "capability": "planner_reasoning",
                "kind": "llm_call",
                "provider": "openai",
                "model": "gpt-5.4-mini",
                "tokens_in": 500,
                "tokens_out": 80,
                "unit_count": 0,
                "cost_uah": Decimal("0.01"),
                "status": "success",
                "error_text": None,
            },
            {
                "capability": "chat_final",
                "kind": "llm_call",
                "provider": "gemini",
                "model": "gemini-3.1-pro-preview",
                "tokens_in": 1200,
                "tokens_out": 220,
                "unit_count": 0,
                "cost_uah": Decimal("0.17"),
                "status": "success",
                "error_text": None,
            },
        ]

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    monkeypatch.setattr("billing.commands.get_latest_turn_for_account", fake_get_latest_turn)
    monkeypatch.setattr("billing.commands.get_transactions_for_turn", fake_get_transactions_for_turn)

    result = await commands._cmd_balance(
        msg=_msg("/balance last"),
        geometry=_geo(user_id=42),
        args="last",
        billing_ctx=None,
    )

    text = result.response_text or ""
    assert "Breakdown turn-а" in text
    assert "planner_reasoning" in text
    assert "gemini-3.1-pro-preview" in text
    assert "0.18" in text


@pytest.mark.asyncio
async def test_balance_turn_prefix_renders_specific_turn(monkeypatch):
    async def fake_get_account_by_owner(uid):
        return {
            "account_id": 1,
            "balance_uah": Decimal("42.50"),
            "total_spent_uah": Decimal("8"),
            "total_topup_uah": Decimal("50"),
        }

    async def fake_find_turns(account_id, turn_ref, limit=6):
        assert account_id == 1
        assert turn_ref == "abcd1234"
        return [
            {
                "turn_id": "abcd1234-0000-0000-0000-000000000000",
                "total_cost_uah": Decimal("0.18"),
                "status": "completed",
                "route": "search",
                "capability": "chat_final",
                "user_message_text": "Search latest news",
            }
        ]

    async def fake_get_transactions_for_turn(turn_id):
        return [
            {
                "capability": "search_query",
                "kind": "search_api",
                "provider": "brave",
                "model": "brave-search",
                "tokens_in": 0,
                "tokens_out": 0,
                "unit_count": 3,
                "cost_uah": Decimal("0.02"),
                "status": "success",
                "error_text": None,
            }
        ]

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    monkeypatch.setattr("billing.commands.find_turns_for_account", fake_find_turns)
    monkeypatch.setattr("billing.commands.get_transactions_for_turn", fake_get_transactions_for_turn)

    result = await commands._cmd_balance(
        msg=_msg("/balance turn abcd1234"),
        geometry=_geo(user_id=42),
        args="turn abcd1234",
        billing_ctx=None,
    )

    text = result.response_text or ""
    assert "abcd1234-0000" in text
    assert "search_query" in text
    assert "3 units" in text


@pytest.mark.asyncio
async def test_balance_turn_prefix_rejects_ambiguous_match(monkeypatch):
    async def fake_get_account_by_owner(uid):
        return {
            "account_id": 1,
            "balance_uah": Decimal("42.50"),
            "total_spent_uah": Decimal("8"),
            "total_topup_uah": Decimal("50"),
        }

    async def fake_find_turns(account_id, turn_ref, limit=6):
        return [
            {"turn_id": "abcd1234-0000-0000-0000-000000000000"},
            {"turn_id": "abcd1234-9999-0000-0000-000000000000"},
        ]

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    monkeypatch.setattr("billing.commands.find_turns_for_account", fake_find_turns)

    result = await commands._cmd_balance(
        msg=_msg("/balance turn abcd1234"),
        geometry=_geo(user_id=42),
        args="turn abcd1234",
        billing_ctx=None,
    )

    text = result.response_text or ""
    assert "неоднозначний" in text
    assert "abcd1234" in text


# ── /topup ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_topup_invalid_format(monkeypatch):
    result = await commands._cmd_topup(
        msg=_msg("/topup abc"),
        geometry=_geo(user_id=42),
        args="abc",
        billing_ctx=None,
    )
    assert "Формат" in (result.response_text or "") or "/topup" in (result.response_text or "")


@pytest.mark.asyncio
async def test_topup_below_minimum(monkeypatch):
    result = await commands._cmd_topup(
        msg=_msg("/topup 10"),
        geometry=_geo(user_id=42),
        args="10",
        billing_ctx=None,
    )
    assert "50" in (result.response_text or "")


@pytest.mark.asyncio
async def test_topup_no_account(monkeypatch):
    async def fake_get_account_by_owner(uid):
        return None

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    result = await commands._cmd_topup(
        msg=_msg("/topup 100"),
        geometry=_geo(user_id=42),
        args="100",
        billing_ctx=None,
    )
    assert "/start" in (result.response_text or "")


@pytest.mark.asyncio
async def test_topup_creates_row(monkeypatch):
    async def fake_get_account_by_owner(uid):
        return {"account_id": 5}

    calls = []

    async def fake_create_topup(**kwargs):
        calls.append(kwargs)
        return 99

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    monkeypatch.setattr("billing.commands.create_topup", fake_create_topup)

    result = await commands._cmd_topup(
        msg=_msg("/topup 100"),
        geometry=_geo(user_id=42),
        args="100",
        billing_ctx=None,
    )
    assert len(calls) == 1
    assert calls[0]["account_id"] == 5
    assert calls[0]["amount_uah"] == Decimal("100.00")
    assert "100.00" in (result.response_text or "")
    assert "Етапу 5" in (result.response_text or "")


# ── /mode + owner gating ───────────────────────────────────────────────────


def _stub_owner_helpers(monkeypatch, *, account=None, chat=None):
    async def fake_get_account_by_owner(uid):
        return account

    async def fake_get_chat(cid):
        return chat

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    monkeypatch.setattr("billing.commands.get_chat", fake_get_chat)


@pytest.mark.asyncio
async def test_mode_rejects_non_owner(monkeypatch):
    _stub_owner_helpers(
        monkeypatch,
        account={"account_id": 7},
        chat={"owner_account_id": 99},
    )
    result = await commands._cmd_mode(
        msg=_msg("/mode whitelist"),
        geometry=_geo(user_id=42, chat_type="group"),
        args="whitelist",
        billing_ctx=None,
    )
    assert "власник" in (result.response_text or "").lower()


@pytest.mark.asyncio
async def test_mode_rejects_invalid_mode(monkeypatch):
    _stub_owner_helpers(
        monkeypatch,
        account={"account_id": 7},
        chat={"owner_account_id": 7},
    )
    result = await commands._cmd_mode(
        msg=_msg("/mode bogus"),
        geometry=_geo(user_id=42, chat_type="group"),
        args="bogus",
        billing_ctx=None,
    )
    assert "Формат" in (result.response_text or "")


@pytest.mark.asyncio
async def test_mode_updates_policy_for_owner(monkeypatch):
    _stub_owner_helpers(
        monkeypatch,
        account={"account_id": 7},
        chat={"owner_account_id": 7},
    )
    updated: list = []

    async def fake_update(cid, **kw):
        updated.append((cid, kw))

    monkeypatch.setattr("billing.commands.update_chat_policy", fake_update)

    result = await commands._cmd_mode(
        msg=_msg("/mode whitelist", chat_id=100),
        geometry=_geo(user_id=42, chat_type="group"),
        args="whitelist",
        billing_ctx=None,
    )
    assert updated == [(100, {"access_mode": "whitelist"})]
    assert "whitelist" in (result.response_text or "")


# ── /allow + /ban ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allow_requires_known_username(monkeypatch):
    _stub_owner_helpers(
        monkeypatch,
        account={"account_id": 7},
        chat={"owner_account_id": 7},
    )

    async def fake_get_user_by_username(u):
        return None

    monkeypatch.setattr("billing.commands.get_user_by_username", fake_get_user_by_username)
    result = await commands._cmd_allow(
        msg=_msg("/allow @ghost"),
        geometry=_geo(user_id=42, chat_type="group"),
        args="@ghost",
        billing_ctx=None,
    )
    assert "ghost" in (result.response_text or "")


@pytest.mark.asyncio
async def test_allow_upserts_access_row(monkeypatch):
    _stub_owner_helpers(
        monkeypatch,
        account={"account_id": 7},
        chat={"owner_account_id": 7},
    )

    async def fake_get_user_by_username(u):
        return {"user_id": 555}

    upserts: list = []

    async def fake_upsert(cid, uid, role, added_by=None):
        upserts.append((cid, uid, role, added_by))

    monkeypatch.setattr("billing.commands.get_user_by_username", fake_get_user_by_username)
    monkeypatch.setattr("billing.commands.upsert_chat_access", fake_upsert)

    result = await commands._cmd_allow(
        msg=_msg("/allow @friend", chat_id=100),
        geometry=_geo(user_id=42, chat_type="group"),
        args="@friend",
        billing_ctx=None,
    )
    assert upserts == [(100, 555, "allowed", 42)]
    assert "555" in (result.response_text or "")


@pytest.mark.asyncio
async def test_ban_upserts_as_banned(monkeypatch):
    _stub_owner_helpers(
        monkeypatch,
        account={"account_id": 7},
        chat={"owner_account_id": 7},
    )

    async def fake_get_user_by_username(u):
        return {"user_id": 666}

    upserts: list = []

    async def fake_upsert(cid, uid, role, added_by=None):
        upserts.append((cid, uid, role, added_by))

    monkeypatch.setattr("billing.commands.get_user_by_username", fake_get_user_by_username)
    monkeypatch.setattr("billing.commands.upsert_chat_access", fake_upsert)

    await commands._cmd_ban(
        msg=_msg("/ban @spammer", chat_id=100),
        geometry=_geo(user_id=42, chat_type="group"),
        args="@spammer",
        billing_ctx=None,
    )
    assert upserts == [(100, 666, "banned", 42)]


@pytest.mark.asyncio
async def test_unban_removes_row(monkeypatch):
    _stub_owner_helpers(
        monkeypatch,
        account={"account_id": 7},
        chat={"owner_account_id": 7},
    )

    async def fake_get_user_by_username(u):
        return {"user_id": 666}

    removed: list = []

    async def fake_remove(cid, uid):
        removed.append((cid, uid))

    monkeypatch.setattr("billing.commands.get_user_by_username", fake_get_user_by_username)
    monkeypatch.setattr("billing.commands.remove_chat_access", fake_remove)

    await commands._cmd_unban(
        msg=_msg("/unban @spammer", chat_id=100),
        geometry=_geo(user_id=42, chat_type="group"),
        args="@spammer",
        billing_ctx=None,
    )
    assert removed == [(100, 666)]


# ── /cap ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cap_updates_policy(monkeypatch):
    _stub_owner_helpers(
        monkeypatch,
        account={"account_id": 7},
        chat={"owner_account_id": 7},
    )
    updated: list = []

    async def fake_update(cid, **kw):
        updated.append((cid, kw))

    monkeypatch.setattr("billing.commands.update_chat_policy", fake_update)

    await commands._cmd_cap(
        msg=_msg("/cap user 10", chat_id=100),
        geometry=_geo(user_id=42, chat_type="group"),
        args="user 10",
        billing_ctx=None,
    )
    assert updated[0] == (100, {"per_user_daily_cap_uah": Decimal("10")})

    updated.clear()
    await commands._cmd_cap(
        msg=_msg("/cap chat 100", chat_id=100),
        geometry=_geo(user_id=42, chat_type="group"),
        args="chat 100",
        billing_ctx=None,
    )
    assert updated[0] == (100, {"per_chat_daily_cap_uah": Decimal("100")})


@pytest.mark.asyncio
async def test_cap_rejects_invalid(monkeypatch):
    _stub_owner_helpers(
        monkeypatch,
        account={"account_id": 7},
        chat={"owner_account_id": 7},
    )
    result = await commands._cmd_cap(
        msg=_msg("/cap wrong"),
        geometry=_geo(user_id=42, chat_type="group"),
        args="wrong",
        billing_ctx=None,
    )
    assert "Формат" in (result.response_text or "")


# ── Dispatcher ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_try_handle_non_command_returns_none(monkeypatch):
    result = await commands.try_handle_command(
        msg=_msg("hello"),
        geometry=_geo(user_id=42),
        billing_ctx=None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_try_handle_dispatches(monkeypatch):
    async def fake_get_account_by_owner(uid):
        return None

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    result = await commands.try_handle_command(
        msg=_msg("/balance"),
        geometry=_geo(user_id=42),
        billing_ctx=None,
    )
    assert result is not None
    assert result.handled is True
    assert result.capability == "command_balance"


@pytest.mark.asyncio
async def test_try_handle_swallows_exceptions(monkeypatch):
    async def fake_get_account_by_owner(uid):
        raise RuntimeError("boom")

    monkeypatch.setattr("billing.commands.get_account_by_owner", fake_get_account_by_owner)
    result = await commands.try_handle_command(
        msg=_msg("/balance"),
        geometry=_geo(user_id=42),
        billing_ctx=None,
    )
    assert result is not None
    assert result.finalize_status == "failed"


@pytest.mark.asyncio
async def test_model_command_returns_inline_markup(monkeypatch):
    async def fake_get_user_settings(user_id):
        return {}

    monkeypatch.setattr("billing.commands.get_user_settings", fake_get_user_settings)

    result = await commands._cmd_model(
        msg=_msg("/model"),
        geometry=_geo(user_id=42),
        args="",
        billing_ctx=None,
    )

    assert result.handled is True
    assert result.response_markup is not None
    assert "Персональний вибір моделей" in (result.response_text or "")


@pytest.mark.asyncio
async def test_settings_command_appends_policy_and_markup(monkeypatch):
    async def fake_get_user_settings(user_id):
        return {}

    async def fake_ensure_chat_policy(chat_id):
        return {
            "access_mode": "whitelist",
            "per_user_daily_cap_uah": Decimal("5"),
            "per_chat_daily_cap_uah": Decimal("50"),
        }

    monkeypatch.setattr("billing.commands.get_user_settings", fake_get_user_settings)
    monkeypatch.setattr("billing.commands.ensure_chat_policy", fake_ensure_chat_policy)

    result = await commands._cmd_settings(
        msg=_msg("/settings", chat_id=100),
        geometry=_geo(user_id=42, chat_type="group"),
        args="",
        billing_ctx=None,
    )

    assert result.response_markup is not None
    assert "Політика чату" in (result.response_text or "")
    assert "whitelist" in (result.response_text or "")


@pytest.mark.asyncio
async def test_model_callback_select_persists_settings(monkeypatch):
    stored = {}

    async def fake_provider_available(provider_slug):
        return True

    async def fake_get_user_settings(user_id):
        return dict(stored)

    async def fake_set_user_setting(user_id, key, value):
        if value is None:
            stored.pop(key, None)
        else:
            stored[key] = value

    monkeypatch.setattr("billing.commands._provider_available", fake_provider_available)
    monkeypatch.setattr("billing.commands.get_user_settings", fake_get_user_settings)
    monkeypatch.setattr("billing.commands.set_user_setting", fake_set_user_setting)

    edits = {}
    answers = []

    class DummyCallback:
        data = "mtmodel:select:chat:gemini:gemini-2.5-pro"
        from_user = SimpleNamespace(id=42)
        message = SimpleNamespace(chat_id=100, message_id=7)

        async def answer(self, text=None, show_alert=False):
            answers.append((text, show_alert))

        async def edit_message_text(self, text, **kwargs):
            edits["text"] = text
            edits["kwargs"] = kwargs

    update = SimpleNamespace(callback_query=DummyCallback())

    handled = await commands.try_handle_callback(update, "smartest_bot")

    assert handled is True
    assert stored["chat_provider"] == "gemini"
    assert stored["chat_model"] == "gemini-2.5-pro"
    assert "gemini-2.5-pro" in edits["text"]
    assert answers
