from __future__ import annotations

import pytest

import agent.runner as runner
from agent.search_task import NormalizedResult, SearchEvaluation, SearchTask

CHAT = 99903


def _result(
    title: str,
    url: str,
    snippet: str,
    *,
    provider: str = "test",
) -> NormalizedResult:
    return NormalizedResult(
        url=url,
        title=title,
        snippet=snippet,
        relevance_score=0.8,
        source_provider=provider,
        domain=runner.urllib.parse.urlparse(url).netloc.replace("www.", ""),
    )


class _DummyResponse:
    def __init__(self, content: str):
        class _Obj:
            pass

        self.choices = [_Obj()]
        self.choices[0].message = _Obj()
        self.choices[0].message.tool_calls = None
        self.choices[0].message.content = content


@pytest.mark.asyncio
async def test_explicit_search_appends_search_memory_event(monkeypatch):
    appended = []

    async def fake_build_search_tasks(_chat_id, user_text, **_kwargs):
        return [
            SearchTask(
                original_request=user_text,
                query="NASA Moon mission latest news",
                source="direct_normalized",
                used_context=False,
                reason="test",
                mode="news",
                profile="news",
            )
        ]

    async def fake_select_context(*_args, **_kwargs):
        return []

    async def fake_search(_query, max_results=None, recency_days=None, **kwargs):
        del max_results, recency_days, kwargs
        return [
            _result(
                "NASA Artemis",
                "https://www.nasa.gov/missions/artemis/",
                "NASA update on Moon missions",
                provider="openai_search",
            ),
            _result(
                "AP Artemis",
                "https://apnews.com/article/moon-mission",
                "AP report on Moon mission",
                provider="openai_search",
            ),
            _result(
                "Space.com Artemis",
                "https://www.space.com/artemis-update",
                "Space.com update on Artemis",
                provider="openai_search",
            ),
        ]

    def fake_chat_once(*_args, **_kwargs):
        return _DummyResponse("NASA летить до Місяця.")

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(runner, "build_search_tasks", fake_build_search_tasks)
    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
    monkeypatch.setattr(runner.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(runner.memory_manager, "ensure_budget", fake_budget)
    monkeypatch.setattr(runner, "search_web", fake_search)
    monkeypatch.setattr(runner, "chat_once", fake_chat_once)
    monkeypatch.setattr(
        runner,
        "evaluate_search_step",
        lambda *_args, **_kwargs: SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason="enough",
        ),
    )

    out = await runner.run_agent(CHAT, "Пошукай там піндоси на місяць полетіли чи шо")

    assert "NASA летить до Місяця." in out
    assert appended
    assert appended[-1][1] == "system"
    assert appended[-1][2].startswith("[SEARCH]")
    assert "NASA Moon mission latest news" in appended[-1][2]
    assert "NASA Artemis" in appended[-1][2]
