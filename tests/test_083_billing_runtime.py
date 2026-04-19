"""Tests for billing.runtime — ContextVar isolation and async propagation."""
from __future__ import annotations

import asyncio

import pytest

from billing.context import BillingContext
from billing.runtime import (
    current_billing_context,
    use_billing_context,
)


def _ctx(turn_id: str = "t-1") -> BillingContext:
    return BillingContext(
        turn_id=turn_id,
        account_id=10,
        chat_id=20,
        user_id=30,
    )


@pytest.mark.asyncio
async def test_default_context_is_none():
    assert current_billing_context() is None


@pytest.mark.asyncio
async def test_use_billing_context_sets_and_restores():
    assert current_billing_context() is None
    ctx = _ctx()
    async with use_billing_context(ctx):
        assert current_billing_context() is ctx
    assert current_billing_context() is None


@pytest.mark.asyncio
async def test_nested_contexts_restore_outer():
    outer = _ctx("outer")
    inner = _ctx("inner")
    async with use_billing_context(outer):
        assert current_billing_context().turn_id == "outer"
        async with use_billing_context(inner):
            assert current_billing_context().turn_id == "inner"
        assert current_billing_context().turn_id == "outer"
    assert current_billing_context() is None


@pytest.mark.asyncio
async def test_context_propagates_to_child_task():
    ctx = _ctx("parent")
    captured: list[BillingContext | None] = []

    async def child() -> None:
        captured.append(current_billing_context())

    async with use_billing_context(ctx):
        await asyncio.create_task(child())

    assert captured == [ctx]


@pytest.mark.asyncio
async def test_sibling_tasks_have_isolated_contexts():
    captured: dict[str, BillingContext | None] = {}

    async def worker(name: str) -> None:
        async with use_billing_context(_ctx(name)):
            await asyncio.sleep(0)
            captured[name] = current_billing_context()

    await asyncio.gather(worker("a"), worker("b"))
    assert captured["a"].turn_id == "a"
    assert captured["b"].turn_id == "b"


@pytest.mark.asyncio
async def test_exception_inside_block_still_resets():
    ctx = _ctx()
    with pytest.raises(RuntimeError):
        async with use_billing_context(ctx):
            assert current_billing_context() is ctx
            raise RuntimeError("boom")
    assert current_billing_context() is None
