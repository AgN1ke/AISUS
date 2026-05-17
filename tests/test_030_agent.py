from __future__ import annotations

import asyncio
import os

import pytest

import agent.runner as runner
from agent.runner import _should_use_agent, run_agent
from agent.search_task import NormalizedResult, SearchEvaluation, SearchTask

CHAT = 99903


def _result(
    title: str,
    url: str,
    snippet: str,
    *,
    provider: str = "test",
    domain: str | None = None,
    content: str | None = None,
) -> NormalizedResult:
    return NormalizedResult(
        url=url,
        title=title,
        snippet=snippet,
        relevance_score=0.8,
        source_provider=provider,
        domain=domain or runner.urllib.parse.urlparse(url).netloc.replace("www.", ""),
        has_full_content=bool(content),
        full_content=content,
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
async def test_run_capability_places_turn_context_after_memory(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_select_context(*_args, **_kwargs):
        return [
            {"role": "system", "content": "[LONG-MEMO] stale cats topic"},
            {"role": "assistant", "content": "old answer about tripillia cats"},
        ]

    def fake_chat_once(messages, **_kwargs):
        captured["messages"] = messages
        return _DummyResponse("shortened current reply")

    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
    monkeypatch.setattr(runner, "chat_once", fake_chat_once)
    monkeypatch.setattr(runner, "capability_model", lambda _capability: "test-model")

    await runner.run_capability(
        CHAT,
        "korotshe",
        turn_context_msgs=[
            {
                "role": "system",
                "content": (
                    "[CHAT-GEOMETRY]\n"
                    "reply_to_bot: true\n"
                    "reply_target_text: current answer about reusable memory package\n"
                    "current_user_text: korotshe"
                ),
            }
        ],
    )

    messages = captured["messages"]
    contents = [item["content"] for item in messages]  # type: ignore[index]
    stale_idx = contents.index("old answer about tripillia cats")
    geometry_idx = next(
        i for i, content in enumerate(contents) if content.startswith("[CHAT-GEOMETRY]")
    )
    final_user_idx = len(contents) - 1

    assert stale_idx < geometry_idx < final_user_idx
    assert contents[final_user_idx] == "korotshe"


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
async def test_should_use_agent_strict():
    os.environ["THINKING_STRICT"] = "1"
    assert _should_use_agent("/think що нового") is True
    assert _should_use_agent("звичайне питання") is False


@pytest.mark.asyncio
@pytest.mark.skip(reason="search_synthesis layer removed in session 099 redesign")
async def test_explicit_search_pipeline(monkeypatch):
    called: dict[str, object] = {}

    async def fake_build_search_tasks(_chat_id, user_text, **_kwargs):
        return [
            SearchTask(
                original_request=user_text,
                query="новини дня",
                source="test",
                used_context=False,
                reason="test",
                mode="news",
                profile="news",
                preferred_domains=("openai.com", "reuters.com"),
            )
        ]

    async def fake_select_context(*_args, **_kwargs):
        return [{"role": "assistant", "content": "старий контекст"}]

    async def fake_search(query, max_results=None, recency_days=None, **kwargs):
        called["query"] = query
        called["max_results"] = max_results
        called["recency_days"] = recency_days
        called["mode"] = kwargs.get("mode")
        called["preferred_domains"] = kwargs.get("preferred_domains")
        return [
            _result("Новина A", "https://a.test", "Короткий опис A"),
            _result("Новина B", "https://b.test", "Короткий опис B"),
            _result("Новина C", "https://c.test", "Короткий опис C"),
        ]

    def fake_chat_once(
        messages, tools=None, use_reasoning=False, model=None, **_kwargs
    ):
        called["tools"] = tools
        called["use_reasoning"] = use_reasoning
        called["messages"] = messages
        called["model"] = model
        return _DummyResponse("Ось коротка відповідь за результатами пошуку.")

    monkeypatch.setattr(runner, "build_search_tasks", fake_build_search_tasks)
    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
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

    out = await run_agent(CHAT, "пошукай новини дня")

    assert called["query"] == "новини дня"
    assert called["max_results"] == 5
    assert called["mode"] == "news"
    assert called["preferred_domains"]
    assert called["tools"] is None
    assert called["model"] is not None
    assert "Ось коротка відповідь" in out
    assert "[[1]](" in out
    assert "Джерела" not in out


@pytest.mark.asyncio
@pytest.mark.skip(reason="search_synthesis layer removed in session 099 redesign")
async def test_explicit_search_retry_pipeline(monkeypatch):
    queries: list[tuple[str, int | None, int | None]] = []
    fetched: list[str] = []

    async def fake_build_search_tasks(_chat_id, user_text, **_kwargs):
        return [
            SearchTask(
                original_request=user_text,
                query="перший запит",
                source="test",
                used_context=True,
                reason="test",
                need_extract=True,
            )
        ]

    async def fake_select_context(*_args, **_kwargs):
        return []

    async def fake_search(query, max_results=None, recency_days=None, **kwargs):
        queries.append((query, max_results, recency_days))
        if query == "перший запит":
            return [_result("Чернетка", "https://draft.test", "Неповний результат")]
        return [
            _result("Підтвердження", "https://confirmed.test", "Уточнений результат")
        ]

    async def fake_extract(
        _query,
        results,
        *,
        max_pages,
        max_chars,
        profile="general",
        need_primary_source=False,
    ):
        del max_chars, profile, need_primary_source
        fetched.extend(item.url for item in results)
        return [
            item.with_full_content(f"TEXT({item.url})") for item in results[:max_pages]
        ]

    def fake_evaluate(_original_request, query, _results, _pages):
        if query == "перший запит":
            return SearchEvaluation(
                sufficient=False,
                should_retry=True,
                retry_query="уточнений запит",
                reason="too_broad",
            )
        return SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason="confirmed",
        )

    def fake_chat_once(
        messages, tools=None, use_reasoning=False, model=None, **_kwargs
    ):
        del messages, tools, use_reasoning, model
        return _DummyResponse("Остаточна відповідь після повторного пошуку.")

    monkeypatch.setattr(runner, "build_search_tasks", fake_build_search_tasks)
    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
    monkeypatch.setattr(runner, "search_web", fake_search)
    monkeypatch.setattr(runner, "extract_search_pages", fake_extract)
    monkeypatch.setattr(runner, "evaluate_search_step", fake_evaluate)
    monkeypatch.setattr(runner, "chat_once", fake_chat_once)

    out = await run_agent(CHAT, "загугли")

    assert [item[0] for item in queries] == ["перший запит", "уточнений запит"]
    assert fetched == ["https://draft.test", "https://confirmed.test"]
    assert "Остаточна відповідь після повторного пошуку." in out
    assert "[[1]](" in out
    assert "Джерела" not in out


@pytest.mark.asyncio
@pytest.mark.skip(reason="search_synthesis layer removed in session 099 redesign")
async def test_explicit_search_decomposition_runs_all_planned_queries(monkeypatch):
    queries: list[str] = []

    async def fake_build_search_tasks(_chat_id, user_text, **_kwargs):
        return [
            SearchTask(
                original_request=user_text,
                query="OpenAI latest news",
                source="query_planner",
                used_context=False,
                reason="planned_subquery:news",
                mode="news",
                profile="news",
                alternative_queries=("OpenAI new announcements latest news",),
            ),
            SearchTask(
                original_request=user_text,
                query="Anthropic latest news",
                source="query_planner",
                used_context=False,
                reason="planned_subquery:news",
                mode="news",
                profile="news",
                alternative_queries=("Anthropic new announcements latest news",),
            ),
        ]

    async def fake_select_context(*_args, **_kwargs):
        return []

    async def fake_search(query, max_results=None, recency_days=None, **kwargs):
        del max_results, recency_days, kwargs
        queries.append(query)
        if query.startswith("OpenAI"):
            return [
                _result("OpenAI", "https://openai.com/news", "OpenAI latest update")
            ]
        return [
            _result(
                "Anthropic",
                "https://www.anthropic.com/news",
                "Anthropic latest update",
            )
        ]

    def fake_chat_once(
        messages, tools=None, use_reasoning=False, model=None, **_kwargs
    ):
        called_prompt = messages[-1]["content"]
        assert "Evidence:\n[1] OpenAI" in called_prompt
        assert "[2] Anthropic" in called_prompt
        assert "Заплановані пошукові підзапити" not in called_prompt
        return _DummyResponse("Ось порівняльний результат за двома підзапитами.")

    monkeypatch.setattr(runner, "build_search_tasks", fake_build_search_tasks)
    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
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

    out = await run_agent(CHAT, "порівняй новини про OpenAI і Anthropic")

    assert queries == ["OpenAI latest news", "Anthropic latest news"]
    assert "Ось порівняльний результат за двома підзапитами." in out
    assert "[[1]](" in out
    assert "Джерела" not in out


@pytest.mark.asyncio
@pytest.mark.skip(reason="search_synthesis layer removed in session 099 redesign")
async def test_explicit_search_runs_sub_queries_in_parallel(monkeypatch):
    in_flight = 0
    max_in_flight = 0

    async def fake_build_search_tasks(_chat_id, user_text, **_kwargs):
        return [
            SearchTask(
                original_request=user_text,
                query="OpenAI latest news",
                source="query_planner",
                used_context=False,
                reason="planned_subquery:news",
                mode="news",
                profile="news",
            ),
            SearchTask(
                original_request=user_text,
                query="Anthropic latest news",
                source="query_planner",
                used_context=False,
                reason="planned_subquery:news",
                mode="news",
                profile="news",
            ),
        ]

    async def fake_select_context(*_args, **_kwargs):
        return []

    async def fake_search(query, max_results=None, recency_days=None, **kwargs):
        del max_results, recency_days, kwargs
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        slug = query.split()[0].lower()
        return [_result(query, f"https://example.com/{slug}", "Snippet")]

    def fake_evaluate(_plan, _evidence, attempt):
        assert attempt == 1
        return SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason="enough",
            coverage={
                "OpenAI latest news": True,
                "Anthropic latest news": True,
            },
        )

    def fake_chat_once(*_args, **_kwargs):
        return _DummyResponse("Паралельний пошук спрацював.")

    monkeypatch.setattr(runner, "build_search_tasks", fake_build_search_tasks)
    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
    monkeypatch.setattr(runner, "search_web", fake_search)
    monkeypatch.setattr(runner, "evaluate_evidence", fake_evaluate)
    monkeypatch.setattr(runner, "chat_once", fake_chat_once)

    out = await run_agent(CHAT, "порівняй новини про OpenAI і Anthropic")

    assert max_in_flight > 1
    assert "Паралельний пошук спрацював." in out


@pytest.mark.asyncio
@pytest.mark.skip(reason="search_synthesis layer removed in session 099 redesign")
async def test_explicit_search_returns_clean_failure_on_junk_evidence(monkeypatch):
    async def fake_build_search_tasks(_chat_id, user_text, **_kwargs):
        return [
            SearchTask(
                original_request=user_text,
                query="США полетіли на Місяць",
                source="test",
                used_context=True,
                reason="test",
            )
        ]

    async def fake_select_context(*_args, **_kwargs):
        return []

    async def fake_search(_query, max_results=None, recency_days=None, **kwargs):
        del max_results, recency_days, kwargs
        return [
            _result(
                "Question on Zhihu",
                "https://www.zhihu.com/question/123",
                "random forum text",
            )
        ]

    called = {"chat_once": 0}

    def fake_chat_once(*_args, **_kwargs):
        called["chat_once"] += 1
        raise AssertionError("search synthesis should not run on junk evidence")

    monkeypatch.setattr(runner, "build_search_tasks", fake_build_search_tasks)
    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
    monkeypatch.setattr(runner, "search_web", fake_search)
    monkeypatch.setattr(
        runner,
        "evaluate_search_step",
        lambda *_args, **_kwargs: SearchEvaluation(
            sufficient=False,
            should_retry=False,
            retry_query="",
            reason="junk",
        ),
    )
    monkeypatch.setattr(
        runner,
        "evaluate_evidence",
        lambda *_args, **_kwargs: SearchEvaluation(
            sufficient=False,
            should_retry=False,
            retry_query="",
            reason="junk",
            coverage={"США полетіли на Місяць": False},
        ),
    )
    monkeypatch.setattr(runner, "chat_once", fake_chat_once)

    out = await run_agent(CHAT, "ну загугли")

    assert called["chat_once"] == 0
    assert "Не зміг зібрати достатньо надійних джерел" in out
