from __future__ import annotations

import pytest

import agent.runner as runner
from agent.search_task import NormalizedResult

CHAT = 99903


def _result() -> NormalizedResult:
    return NormalizedResult(
        url="https://www.nasa.gov/missions/artemis/",
        title="NASA Artemis",
        snippet="NASA update on Moon missions",
        relevance_score=0.8,
        source_provider="openai_search",
        domain="nasa.gov",
    )


class _DummyResponse:
    def __init__(self, content: str):
        class _Obj:
            pass

        self.choices = [_Obj()]
        self.choices[0].message = _Obj()
        self.choices[0].message.tool_calls = None
        self.choices[0].message.content = content


def _tool_response(name: str, arguments: str):
    class _Obj:
        pass

    response = _Obj()
    response.choices = [_Obj()]
    response.choices[0].message = _Obj()
    response.choices[0].message.content = ""
    response.choices[0].message.tool_calls = [_Obj()]
    tool_call = response.choices[0].message.tool_calls[0]
    tool_call.id = "tool-1"
    tool_call.function = _Obj()
    tool_call.function.name = name
    tool_call.function.arguments = arguments
    return response


@pytest.mark.asyncio
async def test_agent_tool_loop_serializes_normalized_results(monkeypatch):
    calls = {"chat_once": 0, "tool_payload": None}

    async def fake_select_context(*_args, **_kwargs):
        return []

    async def fake_search(query, max_results=None, recency_days=None, **kwargs):
        del query, max_results, recency_days, kwargs
        return [_result()]

    def fake_make_messages(*_args, **_kwargs):
        return []

    def fake_chat_once(
        messages, tools=None, use_reasoning=False, capability=None, **_kwargs
    ):
        del tools, use_reasoning, capability
        calls["chat_once"] += 1
        if calls["chat_once"] == 1:
            return _tool_response(
                "search_web",
                '{"query": "NASA Moon mission latest news", "max_results": 5, "recency_days": 7}',
            )
        calls["tool_payload"] = messages[-1]["content"]
        return _DummyResponse("Ось відповідь після tool loop.")

    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
    monkeypatch.setattr(runner, "search_web", fake_search)
    monkeypatch.setattr(runner, "make_messages", fake_make_messages)
    monkeypatch.setattr(runner, "chat_once", fake_chat_once)
    monkeypatch.setattr(runner, "tool_spec", lambda: [{"name": "search_web"}])
    monkeypatch.setattr(runner, "_is_explicit_search_intent", lambda _text: False)
    monkeypatch.setenv("SEARCH_ENABLED", "true")

    out = await runner.run_agent(CHAT, "розбери новини про NASA")

    assert "Ось відповідь після tool loop." in out
    assert calls["tool_payload"] is not None
    assert '"url": "https://www.nasa.gov/missions/artemis/"' in calls["tool_payload"]
