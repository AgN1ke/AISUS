import agent.search_task as search_task
from agent.search_task import EvidencePack, SearchPlan, SubQuery


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


def test_evaluate_search_step_keeps_heuristic_success_when_llm_wants_retry(
    monkeypatch,
):
    def fake_chat_once(*_args, **_kwargs):
        return DummyResponse(
            '{"sufficient":false,"retry_query":"OpenAI latest news April 2026","reason":"want_more_pages"}'
        )

    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    evaluation = search_task.evaluate_search_step(
        "що нового в OpenAI сьогодні",
        "OpenAI latest news",
        [
            {
                "title": "OpenAI company announcements",
                "url": "https://openai.com/news/company-announcements/",
                "snippet": "Latest OpenAI news.",
            },
            {
                "title": "AP coverage",
                "url": "https://apnews.com/article/openai-news",
                "snippet": "AP article about OpenAI.",
            },
            {
                "title": "TechCrunch coverage",
                "url": "https://techcrunch.com/openai-news",
                "snippet": "TechCrunch article about OpenAI.",
            },
        ],
        [],
    )

    assert evaluation.sufficient is True
    assert evaluation.should_retry is False
    assert evaluation.retry_query == ""


def test_evaluate_evidence_targets_missing_sub_query_retry(monkeypatch):
    def fake_chat_once(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    plan = SearchPlan(
        sub_queries=(
            SubQuery(query="OpenAI latest news", profile="news"),
            SubQuery(
                query="Anthropic latest news",
                profile="news",
                alternative="Anthropic announcements latest news",
            ),
        ),
        original_request="порівняй новини про OpenAI і Anthropic",
    )
    evidence = EvidencePack(
        results=[
            search_task.NormalizedResult.from_dict(
                {
                    "title": "OpenAI launch",
                    "url": "https://openai.com/news/launch",
                    "snippet": "OpenAI launched something new.",
                    "relevance_score": 0.9,
                    "source_provider": "brave_search",
                }
            )
        ],
        sub_query_coverage={
            "OpenAI latest news": True,
            "Anthropic latest news": False,
        },
        total_providers_used=1,
        total_results_before_filter=1,
        retry_queries={
            "Anthropic latest news": "Anthropic announcements latest news",
        },
    )

    evaluation = search_task.evaluate_evidence(plan, evidence, attempt=1)

    assert evaluation.sufficient is False
    assert evaluation.should_retry is True
    assert evaluation.retry_query == "Anthropic announcements latest news"
    assert evaluation.retry_sub_query is not None
    assert evaluation.retry_sub_query.query == "Anthropic latest news"
    assert evaluation.coverage == {
        "OpenAI latest news": True,
        "Anthropic latest news": False,
    }


def test_evaluate_evidence_rejects_low_relevance_hits(monkeypatch):
    def fake_chat_once(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    plan = SearchPlan(
        sub_queries=(SubQuery(query="Moon mission latest news", profile="news"),),
        original_request="що нового про місію на Місяць",
    )
    evidence = EvidencePack(
        results=[
            search_task.NormalizedResult.from_dict(
                {
                    "title": "Weak result 1",
                    "url": "https://example.com/one",
                    "snippet": "Barely related text",
                    "relevance_score": 0.2,
                    "source_provider": "brave_search",
                }
            ),
            search_task.NormalizedResult.from_dict(
                {
                    "title": "Weak result 2",
                    "url": "https://example.org/two",
                    "snippet": "Another weak result",
                    "relevance_score": 0.25,
                    "source_provider": "brave_search",
                }
            ),
            search_task.NormalizedResult.from_dict(
                {
                    "title": "Weak result 3",
                    "url": "https://example.net/three",
                    "snippet": "Still weak",
                    "relevance_score": 0.1,
                    "source_provider": "brave_search",
                }
            ),
        ],
        sub_query_coverage={"Moon mission latest news": True},
        total_providers_used=1,
        total_results_before_filter=3,
    )

    evaluation = search_task.evaluate_evidence(plan, evidence, attempt=1)

    assert evaluation.sufficient is False
    assert evaluation.reason in {"low_relevance_results", "query_anchor_mismatch"}


def test_evaluate_search_step_rejects_high_score_topic_mismatch(monkeypatch):
    def fake_chat_once(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    evaluation = search_task.evaluate_search_step(
        "що нового про місію NASA на Місяць",
        "NASA Moon mission latest news",
        [
            {
                "title": "NASA Mars rover update",
                "url": "https://www.nasa.gov/missions/mars-rover/",
                "snippet": "NASA shares a Mars rover update.",
                "relevance_score": 0.95,
                "source_provider": "brave_search",
            },
            {
                "title": "NASA ISS update",
                "url": "https://www.nasa.gov/international-space-station/",
                "snippet": "NASA reports an ISS crew update.",
                "relevance_score": 0.9,
                "source_provider": "brave_search",
            },
        ],
        [],
    )

    assert evaluation.sufficient is False
    assert evaluation.reason == "query_anchor_mismatch"


def test_evaluate_search_step_accepts_required_anchors_in_url(monkeypatch):
    def fake_chat_once(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(search_task, "chat_once", fake_chat_once)

    evaluation = search_task.evaluate_search_step(
        "яка погода в києві буде у вівторок?",
        "погода Київ 2026-05-05",
        [
            {
                "title": "Погода на 5 травня",
                "url": "https://sinoptik.ua/pohoda/kyiv/2026-05-05",
                "snippet": "Прогноз без опадів.",
                "relevance_score": 0.8,
                "source_provider": "brave_search",
            },
            {
                "title": "Погода Київ",
                "url": "https://meteofor.com.ua/weather-kyiv/",
                "snippet": "Прогноз погоди для Києва.",
                "relevance_score": 0.7,
                "source_provider": "brave_search",
            },
        ],
        [],
    )

    assert evaluation.sufficient is True
