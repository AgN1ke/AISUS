"""Verify chat_once schedules a billing transaction when context is active."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import agent.llm as llm
from billing.context import BillingContext
from billing.runtime import use_billing_context


def _openai_response(prompt_tokens: int = 100, completion_tokens: int = 50):
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    msg = SimpleNamespace(content="hi", tool_calls=None)
    return SimpleNamespace(usage=usage, choices=[SimpleNamespace(message=msg)])


@pytest.mark.asyncio
async def test_chat_once_with_no_context_does_not_log(monkeypatch):
    calls = []

    async def fake_log(**kwargs):
        calls.append(kwargs)
        return 1

    monkeypatch.setattr("billing.gateway.log_transaction", fake_log)

    fake_response = _openai_response()
    with patch.object(llm, "_dispatch_chat_once", return_value=fake_response):
        result = llm.chat_once(
            [{"role": "user", "content": "hi"}],
            capability="chat_final",
        )
    # Allow scheduled tasks to drain.
    await asyncio.sleep(0)
    assert result is fake_response
    assert calls == []


@pytest.mark.asyncio
async def test_chat_once_with_context_schedules_log(monkeypatch):
    calls: list[dict] = []

    async def fake_log(**kwargs):
        calls.append(kwargs)
        return 1

    async def fake_compute(**_):
        from decimal import Decimal

        from billing.pricing import CostBreakdown
        return CostBreakdown(
            cost_usd=Decimal("0.001"),
            cost_uah=Decimal("0.04"),
            markup_pct=Decimal("40"),
            uah_per_usd=Decimal("40"),
            source="pricing_table",
        )

    monkeypatch.setattr("billing.gateway.log_transaction", fake_log)
    monkeypatch.setattr("billing.gateway.compute_cost_uah", fake_compute)

    fake_response = _openai_response(prompt_tokens=300, completion_tokens=70)
    ctx = BillingContext(turn_id="abc", account_id=1, chat_id=2, user_id=3)

    with patch.object(llm, "_dispatch_chat_once", return_value=fake_response):
        async with use_billing_context(ctx):
            llm.chat_once(
                [{"role": "user", "content": "hi"}],
                capability="planner",
            )
            # Drain the fire-and-forget task.
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    assert len(calls) == 1
    entry = calls[0]
    assert entry["turn_id"] == "abc"
    assert entry["account_id"] == 1
    assert entry["chat_id"] == 2
    assert entry["user_id"] == 3
    assert entry["tokens_in"] == 300
    assert entry["tokens_out"] == 70
    assert entry["capability"] == "planner"
    assert entry["status"] == "success"


@pytest.mark.asyncio
async def test_chat_once_failure_logs_failed_transaction(monkeypatch):
    calls: list[dict] = []

    async def fake_log(**kwargs):
        calls.append(kwargs)
        return 1

    async def fake_compute(**_):
        from decimal import Decimal
        from billing.pricing import CostBreakdown
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
    with patch.object(llm, "_dispatch_chat_once", side_effect=RuntimeError("oops")):
        async with use_billing_context(ctx):
            with pytest.raises(RuntimeError):
                llm.chat_once(
                    [{"role": "user", "content": "hi"}],
                    capability="chat_final",
                )
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    assert len(calls) == 1
    assert calls[0]["status"] == "failed"
    assert "oops" in (calls[0]["error_text"] or "")
