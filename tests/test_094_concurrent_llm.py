from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

import agent.runner as runner
import app.message_logic as message_logic
from agent.planner import PlanDecision
from adapters.base import MessageGeometry
from billing.context import BillingContext
from billing.runtime import current_billing_context, use_billing_context


class DummyResponse:
    def __init__(self, content: str):
        message = SimpleNamespace(content=content, tool_calls=None)
        choice = SimpleNamespace(message=message)
        self.choices = [choice]


@pytest.mark.asyncio
async def test_run_capability_offloads_chat_once_to_threads(monkeypatch):
    async def fake_select_context(*_args, **_kwargs):
        return []

    state = {"in_flight": 0, "max_in_flight": 0}
    lock = threading.Lock()

    def fake_chat_once(*_args, **_kwargs):
        with lock:
            state["in_flight"] += 1
            state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        try:
            time.sleep(0.05)
            return DummyResponse("ok")
        finally:
            with lock:
                state["in_flight"] -= 1

    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
    monkeypatch.setattr(runner, "chat_once", fake_chat_once)

    started_at = time.perf_counter()
    results = await asyncio.gather(
        *(runner.run_capability(1000 + i, "test capability") for i in range(8))
    )
    elapsed = time.perf_counter() - started_at

    assert results == ["ok"] * 8
    assert state["max_in_flight"] >= 2
    assert elapsed < 0.35


@pytest.mark.asyncio
async def test_run_capability_preserves_billing_context_inside_thread(monkeypatch):
    async def fake_select_context(*_args, **_kwargs):
        return []

    captured: list[str | None] = []

    def fake_chat_once(*_args, **_kwargs):
        ctx = current_billing_context()
        captured.append(ctx.turn_id if ctx else None)
        return DummyResponse("ok")

    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
    monkeypatch.setattr(runner, "chat_once", fake_chat_once)

    ctx = BillingContext(
        turn_id="turn-thread",
        account_id=10,
        chat_id=20,
        user_id=30,
    )
    async with use_billing_context(ctx):
        result = await runner.run_capability(20, "context test")

    assert result == "ok"
    assert captured == ["turn-thread"]


@pytest.mark.asyncio
async def test_plan_execution_offloads_planner_call(monkeypatch):
    async def fake_fetch_recent(*_args, **_kwargs):
        return []

    state = {"in_flight": 0, "max_in_flight": 0}
    lock = threading.Lock()

    def fake_plan_message(_task):
        with lock:
            state["in_flight"] += 1
            state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        try:
            time.sleep(0.05)
            return PlanDecision(
                route="chat",
                capability="chat_final",
                use_reasoning=False,
                planner_source="test_thread_bridge",
                notes="threaded",
            )
        finally:
            with lock:
                state["in_flight"] -= 1

    monkeypatch.setattr(message_logic, "fetch_recent", fake_fetch_recent)
    monkeypatch.setattr(message_logic, "plan_message", fake_plan_message)

    task = message_logic.UserTask(
        instruction="test planner",
        has_media_target=False,
    )
    geometry = MessageGeometry(chat_type="group", addressed=True)
    session = message_logic.SessionState(chat_id=99950, authed=True)

    started_at = time.perf_counter()
    plans = await asyncio.gather(
        message_logic.plan_execution(99950, task, geometry, session),
        message_logic.plan_execution(99951, task, geometry, session),
    )
    elapsed = time.perf_counter() - started_at

    assert [plan.planner_source for plan in plans] == [
        "test_thread_bridge",
        "test_thread_bridge",
    ]
    assert state["max_in_flight"] >= 2
    assert elapsed < 0.10
