from __future__ import annotations

import pytest

import agent.search_task as search_task
from agent.search_task import NormalizedResult


class DummyResponse:
    def __init__(self, content):
        class _Msg:
            pass

        class _Choice:
            pass

        msg = _Msg()
        msg.content = content
        choice = _Choice()
        choice.message = msg
        self.choices = [choice]


def _result(
    title: str,
    url: str,
    snippet: str,
    *,
    domain: str = "example.com",
    content: str | None = None,
) -> NormalizedResult:
    return NormalizedResult(
        url=url,
        title=title,
        snippet=snippet,
        relevance_score=0.8,
        source_provider="test",
        domain=domain,
        has_full_content=bool(content),
        full_content=content,
    )


@pytest.mark.asyncio
async def test_build_search_task_direct_request(monkeypatch):
    async def fake_select_context(*_args, **_kwargs):
        return [{"role": "user", "content": "пошукай новини про OpenAI"}]

    monkeypatch.setattr(
        search_task.memory_manager, "select_context", fake_select_context
    )

    task = await search_task.build_search_task(123, "пошукай новини про OpenAI")

    assert task.query == "новини про OpenAI"
    assert task.source == "direct_normalized"
    assert task.used_context is False
    # mode/profile are defaults — LLM planner assigns them later
    assert task.mode == "general"
    assert task.profile == "general"


@pytest.mark.asyncio
async def test_build_search_task_contextual_followup_uses_composer(monkeypatch):
    async def fake_select_context(*_args, **_kwargs):
        return [
            {
                "role": "user",
                "content": "ти сказав, що OpenAI вже запустила новий реліз",
            },
            {"role": "assistant", "content": "так, наче вже запустила"},
            {"role": "user", "content": "ну загугли"},
        ]

    captured = {}

    def fake_chat_once(messages, **_kwargs):
        captured["messages"] = messages
        return DummyResponse(
            '{"query":"OpenAI latest release news","reason":"context followup","used_context":true}'
        )

    monkeypatch.setattr(
        search_task.memory_manager, "select_context", fake_select_context
    )
    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    task = await search_task.build_search_task(123, "ну загугли")

    assert task.query == "OpenAI latest release news"
    assert task.source == "llm_composer"
    assert task.used_context is True
    assert '"latest_user_message": "ну загугли"' in captured["messages"][1]["content"]


@pytest.mark.asyncio
async def test_build_search_task_uses_geometry_reply_text_on_vague_followup(
    monkeypatch,
):
    async def fake_select_context(*_args, **_kwargs):
        return [{"role": "assistant", "content": "це якийсь сумнівний тейк"}]

    def fake_chat_once(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(
        search_task.memory_manager, "select_context", fake_select_context
    )
    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    task = await search_task.build_search_task(
        123,
        "ну загугли",
        turn_context_msgs=[
            {
                "role": "system",
                "content": (
                    "[CHAT-GEOMETRY]\n"
                    "reply_target_text: США полетіли на Місяць чи ні\n"
                    "reply_target_media_kind: image"
                ),
            }
        ],
    )

    assert "США полетіли на Місяць" in task.query
    assert task.source == "heuristic_context"
    assert task.used_context is True


@pytest.mark.asyncio
async def test_plan_search_queries_decomposes_compound_request(monkeypatch):
    def fake_chat_once(messages, **_kwargs):
        return DummyResponse(
            """
            {
              "sub_queries": [
                {
                  "query": "OpenAI latest news",
                  "profile": "news",
                  "alternative": "OpenAI new announcements",
                  "provider_hint": "brave"
                },
                {
                  "query": "Anthropic latest news",
                  "profile": "news",
                  "alternative": "Anthropic new announcements",
                  "provider_hint": "brave"
                }
              ],
              "needs_extract": false,
              "recency_days": 7
            }
            """
        )

    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    plan = await search_task.plan_search_queries(
        "порівняй новини про OpenAI і Anthropic",
        [{"role": "user", "content": "порівняй новини про OpenAI і Anthropic"}],
        mode_hint="general",
    )

    assert len(plan.sub_queries) == 2
    assert plan.sub_queries[0].query == "OpenAI latest news"
    assert plan.sub_queries[0].profile == "news"
    assert plan.sub_queries[0].alternative == "OpenAI new announcements"
    assert plan.sub_queries[1].query == "Anthropic latest news"
    assert plan.recency_days == 7


@pytest.mark.asyncio
async def test_build_search_tasks_populates_alternative_queries(monkeypatch):
    async def fake_select_context(*_args, **_kwargs):
        return [{"role": "user", "content": "порівняй новини про OpenAI і Anthropic"}]

    def fake_chat_once(*_args, **_kwargs):
        return DummyResponse(
            """
            {
              "sub_queries": [
                {
                  "query": "OpenAI latest news",
                  "profile": "news",
                  "alternative": "OpenAI new announcements",
                  "provider_hint": "brave"
                },
                {
                  "query": "Anthropic latest news",
                  "profile": "news",
                  "alternative": "Anthropic new announcements",
                  "provider_hint": "brave"
                }
              ],
              "needs_extract": false,
              "recency_days": 7
            }
            """
        )

    monkeypatch.setattr(
        search_task.memory_manager, "select_context", fake_select_context
    )
    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    tasks = await search_task.build_search_tasks(
        123,
        "порівняй новини про OpenAI і Anthropic",
    )

    assert len(tasks) == 2
    assert tasks[0].source == "query_planner"
    assert tasks[0].alternative_queries == ("OpenAI new announcements",)
    assert tasks[0].profile == "news"
    assert tasks[0].recency_days == 7
    assert tasks[1].alternative_queries == ("Anthropic new announcements",)


@pytest.mark.asyncio
async def test_build_search_tasks_falls_back_when_planner_invalid(monkeypatch):
    async def fake_select_context(*_args, **_kwargs):
        return [{"role": "user", "content": "порівняй новини про OpenAI і Anthropic"}]

    def fake_chat_once(*_args, **_kwargs):
        return DummyResponse("not json")

    monkeypatch.setattr(
        search_task.memory_manager, "select_context", fake_select_context
    )
    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    tasks = await search_task.build_search_tasks(
        123,
        "порівняй новини про OpenAI і Anthropic",
    )

    # Fallback: single task with the direct normalized query
    assert len(tasks) == 1
    assert tasks[0].source == "heuristic_context"


def test_trim_terminal_user_duplicate():
    context = [
        {"role": "assistant", "content": "старий хід"},
        {"role": "user", "content": "пошукай новини про OpenAI"},
    ]

    trimmed = search_task.trim_terminal_user_duplicate(
        context, "пошукай новини про OpenAI"
    )

    assert trimmed == [{"role": "assistant", "content": "старий хід"}]


def test_normalize_search_query_strips_command_prefix():
    query = search_task.normalize_search_query("пошукай новини про OpenAI")
    assert query == "новини про OpenAI"


def test_normalize_search_query_strips_at_mentions():
    query = search_task.normalize_search_query("пошукай @bot новини про OpenAI")
    assert query == "новини про OpenAI"


def test_results_brief_uses_normalized_result_fields():
    brief = search_task._results_brief(
        [_result("A", "https://example.com/a", "Snippet A")],
        [
            _result(
                "Page A", "https://example.com/a", "Snippet A", content="Full text A"
            )
        ],
    )

    assert brief["results"][0]["title"] == "A"
    assert brief["results"][0]["relevance_score"] == 0.8
    assert brief["pages"][0]["text"] == "Full text A"


def test_evaluate_search_step_heuristic_retry(monkeypatch):
    def fake_chat_once(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    evaluation = search_task.evaluate_search_step(
        "знайди в інтернеті історію компанії OpenAI",
        "OpenAI",
        [],
        [],
    )

    assert evaluation.sufficient is False
    assert evaluation.should_retry is True
    assert "OpenAI" in evaluation.retry_query


def test_evaluate_search_step_accepts_normalized_results(monkeypatch):
    def fake_chat_once(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    evaluation = search_task.evaluate_search_step(
        "what is new in OpenAI",
        "OpenAI latest news",
        [
            _result(
                "OpenAI",
                "https://openai.com/news",
                "Latest model update",
                domain="openai.com",
            ),
            _result(
                "Reuters",
                "https://www.reuters.com/openai",
                "Reuters coverage",
                domain="reuters.com",
            ),
            _result(
                "BBC", "https://www.bbc.com/openai", "BBC coverage", domain="bbc.com"
            ),
        ],
        [],
    )

    assert evaluation.sufficient is True
    assert evaluation.reason == "multiple_search_hits"


def test_is_explicit_search_request():
    assert search_task.is_explicit_search_request("пошукай новини про AI") is True
    assert search_task.is_explicit_search_request("погугли щось") is True
    assert search_task.is_explicit_search_request("загугли це") is True
    assert search_task.is_explicit_search_request("що таке Python") is False
    assert search_task.is_explicit_search_request("") is False


def test_weather_kyiv_task_gets_source_and_retry_hints():
    base = search_task.SearchTask(
        original_request="яка погода в києві буде у вівторок?",
        query="погода Київ 2026-05-05",
        source="test",
    )

    task = search_task._tasks_from_plan(
        base,
        search_task.SearchPlan(
            sub_queries=(),
            original_request=base.original_request,
        ),
    )[0]

    assert "sinoptik.ua" in task.preferred_domains
    assert task.country == "UA"
    assert task.languages == ("uk",)
    assert task.need_extract is True
    assert any("site:sinoptik.ua/pohoda/kyiv" in q for q in task.alternative_queries)


def test_weather_kyiv_rejects_other_city_evidence(monkeypatch):
    def fake_chat_once(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    evaluation = search_task.evaluate_search_step(
        "яка погода в києві буде у вівторок?",
        "погода Київ 2026-05-05",
        [
            _result(
                "Погода у Білій Церкві на 5 травня",
                "https://sinoptik.ua/pohoda/bila-tserkva/2026-05-05",
                "Без опадів, +12...+23.",
                domain="sinoptik.ua",
            )
        ],
        [],
    )

    assert evaluation.sufficient is False
    assert evaluation.should_retry is True
    assert evaluation.reason in {"query_anchor_mismatch", "weather_location_mismatch"}
