from __future__ import annotations

import pytest

import agent.runner as runner
from agent.runner import run_agent
from agent.search_task import NormalizedResult, SearchEvaluation, SearchTask

CHAT = 99943

# Session 099 redesign: search_synthesis layer removed. Web search now hands its
# evidence to chat_final via a [SEARCH-RESULT] system message; chat_final composes
# the user-facing reply. The two tests below exercised the obsolete synthesis prompt
# and citation pipeline, so they are skipped rather than rewritten in place — the
# new flow is covered by test_106_search_flow.
pytestmark = pytest.mark.skip(reason="search_synthesis layer removed in session 099 redesign")


def _result(
    title: str,
    url: str,
    snippet: str,
    *,
    provider: str = "test",
    content: str | None = None,
) -> NormalizedResult:
    return NormalizedResult(
        url=url,
        title=title,
        snippet=snippet,
        relevance_score=0.8,
        source_provider=provider,
        domain=runner.urllib.parse.urlparse(url).netloc.replace("www.", ""),
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
async def test_search_synthesis_hides_planner_trace_and_links_citations(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_build_search_tasks(_chat_id, user_text, **_kwargs):
        return [
            SearchTask(
                original_request=user_text,
                query="NASA Moon mission latest news",
                source="query_planner",
                used_context=True,
                reason="planned_subquery:news",
                mode="news",
                profile="news",
            )
        ]

    async def fake_select_context(*_args, **_kwargs):
        return [
            {"role": "assistant", "content": "Старий хід діалогу."},
            {"role": "system", "content": "[SEARCH]\nrequest: old"},
        ]

    async def fake_search(*_args, **_kwargs):
        return [
            _result(
                "NASA Artemis II",
                "https://www.nasa.gov/missions/artemis-ii/",
                "NASA says Artemis II is the next crewed Moon mission.",
            )
        ]

    def fake_chat_once(messages, **_kwargs):
        captured["messages"] = messages
        return _DummyResponse("Artemis II летить [1].")

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
    monkeypatch.setattr(
        runner,
        "evaluate_evidence",
        lambda *_args, **_kwargs: SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason="enough",
            coverage={"NASA Moon mission latest news": True},
        ),
    )

    out = await run_agent(CHAT, "пошукай новини про Artemis II")

    prompt = captured["messages"][-1]["content"]
    assert "Evidence:\n[1] NASA Artemis II" in prompt
    assert "Заплановані пошукові підзапити" not in prompt
    assert "planned_subquery" not in prompt
    assert "Старий хід діалогу." in prompt
    assert "[[1]](https://www.nasa.gov/missions/artemis-ii/)" in out
    assert "Джерела" not in out


@pytest.mark.asyncio
async def test_search_schedules_extract_before_query_retry(monkeypatch):
    search_calls: list[str] = []
    extract_calls: list[str] = []

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
                need_extract=False,
            )
        ]

    async def fake_select_context(*_args, **_kwargs):
        return []

    async def fake_search(query, *args, **kwargs):
        del args, kwargs
        search_calls.append(query)
        return [
            _result(
                "OpenAI newsroom",
                "https://openai.com/news/",
                "OpenAI published a new newsroom update.",
            )
        ]

    async def fake_extract(
        query,
        results,
        *,
        max_pages,
        max_chars,
        profile="general",
        need_primary_source=False,
    ):
        del max_pages, max_chars, profile, need_primary_source
        extract_calls.append(query)
        return [results[0].with_full_content("Expanded page text for synthesis.")]

    def fake_evaluate_search_step(_request, _query, _results, pages):
        return SearchEvaluation(
            sufficient=bool(pages),
            should_retry=not bool(pages),
            retry_query="OpenAI latest news",
            reason="need_extract" if not pages else "enough",
        )

    def fake_evaluate_evidence(_plan, evidence, attempt):
        if evidence.pages:
            return SearchEvaluation(
                sufficient=True,
                should_retry=False,
                retry_query="",
                reason="enough",
                coverage={"OpenAI latest news": True},
            )
        return SearchEvaluation(
            sufficient=False,
            should_retry=True,
            retry_query="OpenAI latest news",
            reason="need_extract",
            retry_sub_query=runner.SubQuery(query="OpenAI latest news"),
            coverage={"OpenAI latest news": False},
        )

    def fake_chat_once(*_args, **_kwargs):
        return _DummyResponse("Є відповідь [1].")

    monkeypatch.setattr(runner, "build_search_tasks", fake_build_search_tasks)
    monkeypatch.setattr(runner.memory_manager, "select_context", fake_select_context)
    monkeypatch.setattr(runner, "search_web", fake_search)
    monkeypatch.setattr(runner, "extract_search_pages", fake_extract)
    monkeypatch.setattr(runner, "evaluate_search_step", fake_evaluate_search_step)
    monkeypatch.setattr(runner, "evaluate_evidence", fake_evaluate_evidence)
    monkeypatch.setattr(runner, "chat_once", fake_chat_once)

    out = await run_agent(CHAT, "пошукай новини про OpenAI")

    assert search_calls == ["OpenAI latest news", "OpenAI latest news"]
    assert extract_calls == ["OpenAI latest news"]
    assert "[[1]](" in out
