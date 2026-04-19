"""Tests for billing.gateway usage extraction and transaction dispatch."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import billing.gateway as gateway
from billing.context import BillingContext
from billing.pricing import CostBreakdown


def _openai_response(prompt_tokens: int, completion_tokens: int):
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(usage=usage, choices=[])


def test_extract_usage_openai_object():
    response = _openai_response(123, 45)
    tokens_in, tokens_out = gateway._extract_usage(response)
    assert tokens_in == 123
    assert tokens_out == 45


def test_extract_usage_gemini_usage_namespace_with_thoughts():
    response = SimpleNamespace(
        usage=SimpleNamespace(
            promptTokenCount=200,
            candidatesTokenCount=80,
            thoughtsTokenCount=20,
        )
    )
    tokens_in, tokens_out = gateway._extract_usage(response)
    assert tokens_in == 200
    assert tokens_out == 100


def test_extract_usage_dict_gemini_format():
    payload = {
        "usage": {
            "promptTokenCount": 200,
            "candidatesTokenCount": 80,
            "thoughtsTokenCount": 20,
        }
    }
    tokens_in, tokens_out = gateway._extract_usage(payload)
    assert tokens_in == 200
    assert tokens_out == 100


def test_extract_usage_missing_returns_zeros():
    assert gateway._extract_usage(None) == (0, 0)
    assert gateway._extract_usage(SimpleNamespace()) == (0, 0)
    assert gateway._extract_usage({}) == (0, 0)


@pytest.mark.asyncio
async def test_log_llm_transaction_noop_without_context(monkeypatch):
    called = []

    async def fake_log(**kwargs):
        called.append(kwargs)
        return 1

    monkeypatch.setattr("billing.gateway.log_transaction", fake_log)
    result = await gateway.log_llm_transaction(
        _openai_response(10, 20),
        billing_context=None,
        capability="chat_final",
        provider="openai",
        model="gpt-5.4-mini",
    )
    assert result is None
    assert called == []


@pytest.mark.asyncio
async def test_log_llm_transaction_writes_when_context_complete(monkeypatch):
    captured = {}

    async def fake_log(**kwargs):
        captured.update(kwargs)
        return 42

    async def fake_compute(**kwargs):
        return CostBreakdown(
            cost_usd=Decimal("0.001"),
            cost_uah=Decimal("0.04"),
            markup_pct=Decimal("40"),
            uah_per_usd=Decimal("40"),
            source="pricing_table",
        )

    monkeypatch.setattr("billing.gateway.log_transaction", fake_log)
    monkeypatch.setattr("billing.gateway.compute_cost_uah", fake_compute)

    ctx = BillingContext(
        turn_id="abc-123",
        account_id=7,
        chat_id=99,
        user_id=42,
    )
    breakdown = await gateway.log_llm_transaction(
        _openai_response(500, 80),
        billing_context=ctx,
        capability="planner",
        provider="openai",
        model="gpt-5.4-mini",
        latency_ms=120,
    )
    assert breakdown is not None
    assert breakdown.cost_uah == Decimal("0.04")
    assert captured["turn_id"] == "abc-123"
    assert captured["account_id"] == 7
    assert captured["chat_id"] == 99
    assert captured["user_id"] == 42
    assert captured["tokens_in"] == 500
    assert captured["tokens_out"] == 80
    assert captured["capability"] == "planner"
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["latency_ms"] == 120
    assert captured["status"] == "success"


@pytest.mark.asyncio
async def test_log_llm_transaction_overrides_token_counts(monkeypatch):
    captured = {}

    async def fake_log(**kwargs):
        captured.update(kwargs)
        return 1

    async def fake_compute(**kwargs):
        captured["compute_kwargs"] = kwargs
        return CostBreakdown(
            cost_usd=Decimal("0"),
            cost_uah=Decimal("0"),
            markup_pct=Decimal("0"),
            uah_per_usd=Decimal("40"),
            source="pricing_table",
        )

    monkeypatch.setattr("billing.gateway.log_transaction", fake_log)
    monkeypatch.setattr("billing.gateway.compute_cost_uah", fake_compute)

    ctx = BillingContext(turn_id="t", account_id=1, chat_id=2, user_id=3)
    await gateway.log_llm_transaction(
        _openai_response(1, 1),
        billing_context=ctx,
        capability="search_api",
        provider="brave",
        model="brave-search",
        kind="search_api",
        unit_count=3,
        tokens_in_override=0,
        tokens_out_override=0,
    )
    assert captured["unit_count"] == 3
    assert captured["compute_kwargs"]["kind"] == "search"
    assert captured["compute_kwargs"]["unit_count"] == 3


@pytest.mark.asyncio
async def test_log_llm_transaction_records_keypool_success(monkeypatch):
    import billing.keypool as keypool

    captured = {}

    async def fake_log(**kwargs):
        captured["log"] = kwargs
        return 1

    async def fake_compute(**kwargs):
        return CostBreakdown(
            cost_usd=Decimal("0.002"),
            cost_uah=Decimal("0.08"),
            markup_pct=Decimal("40"),
            uah_per_usd=Decimal("40"),
            source="pricing_table",
        )

    async def fake_debit(*args, **kwargs):
        captured["debited"] = True

    async def fake_record_success(key_id, *, cost_usd=0):
        captured["success"] = (key_id, cost_usd)

    monkeypatch.setattr("billing.gateway.log_transaction", fake_log)
    monkeypatch.setattr("billing.gateway.compute_cost_uah", fake_compute)
    monkeypatch.setattr("billing.gateway.debit_account", fake_debit)
    monkeypatch.setattr(keypool, "record_success", fake_record_success)

    ctx = BillingContext(turn_id="abc", account_id=7, chat_id=9, user_id=11)
    await gateway.log_llm_transaction(
        _openai_response(100, 25),
        billing_context=ctx,
        capability="chat_final",
        provider="openai",
        model="gpt-5.4-mini",
        key_id=55,
    )

    assert captured["log"]["key_id"] == 55
    assert captured["success"] == (55, Decimal("0.002"))
    assert captured["debited"] is True


@pytest.mark.asyncio
async def test_log_llm_transaction_records_rate_limit(monkeypatch):
    import billing.keypool as keypool

    captured = {}

    async def fake_log(**kwargs):
        captured["log"] = kwargs
        return 1

    async def fake_compute(**kwargs):
        return CostBreakdown(
            cost_usd=Decimal("0"),
            cost_uah=Decimal("0"),
            markup_pct=Decimal("40"),
            uah_per_usd=Decimal("40"),
            source="pricing_table",
        )

    async def fake_record_rate_limit(key_id, cooldown_seconds=60):
        captured["rate_limit"] = (key_id, cooldown_seconds)

    monkeypatch.setattr("billing.gateway.log_transaction", fake_log)
    monkeypatch.setattr("billing.gateway.compute_cost_uah", fake_compute)
    monkeypatch.setattr(keypool, "record_rate_limit", fake_record_rate_limit)

    ctx = BillingContext(turn_id="abc", account_id=7, chat_id=9, user_id=11)
    await gateway.log_llm_transaction(
        None,
        billing_context=ctx,
        capability="chat_final",
        provider="openai",
        model="gpt-5.4-mini",
        key_id=91,
        status="failed",
        error_text="429 rate limit exceeded",
    )

    assert captured["rate_limit"] == (91, 60)


@pytest.mark.asyncio
async def test_log_llm_transaction_disables_invalid_key(monkeypatch):
    import billing.keypool as keypool

    captured = {}

    async def fake_log(**kwargs):
        captured["log"] = kwargs
        return 1

    async def fake_compute(**kwargs):
        return CostBreakdown(
            cost_usd=Decimal("0"),
            cost_uah=Decimal("0"),
            markup_pct=Decimal("40"),
            uah_per_usd=Decimal("40"),
            source="pricing_table",
        )

    async def fake_record_error(key_id, error_text, *, disable=False):
        captured["error"] = (key_id, error_text, disable)

    monkeypatch.setattr("billing.gateway.log_transaction", fake_log)
    monkeypatch.setattr("billing.gateway.compute_cost_uah", fake_compute)
    monkeypatch.setattr(keypool, "record_error", fake_record_error)

    ctx = BillingContext(turn_id="abc", account_id=7, chat_id=9, user_id=11)
    await gateway.log_llm_transaction(
        None,
        billing_context=ctx,
        capability="chat_final",
        provider="gemini",
        model="gemini-3.1-pro-preview",
        key_id=12,
        status="failed",
        error_text="API_KEY_INVALID",
    )

    assert captured["error"] == (12, "API_KEY_INVALID", True)
