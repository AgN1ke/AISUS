import importlib

import pytest

import agent.tools.web_search as web_search
from agent.search_task import NormalizedResult
from agent.tools.web_search import _filter_and_rank_results


def _result(
    title: str,
    url: str,
    snippet: str,
    provider: str = "test",
    *,
    relevance: float = 0.8,
) -> NormalizedResult:
    return NormalizedResult(
        url=url,
        title=title,
        snippet=snippet,
        relevance_score=relevance,
        source_provider=provider,
        domain=web_search._normalized_domain(url),
    )


def test_filter_and_rank_results_drops_known_junk_domains():
    items = [
        _result(
            "Question on Zhihu",
            "https://www.zhihu.com/question/123",
            "random forum text",
        ),
        _result(
            "NASA Artemis",
            "https://www.nasa.gov/missions/artemis/",
            "NASA updates on Moon missions and Artemis program",
        ),
        _result(
            "Reuters moon mission",
            "https://www.reuters.com/world/us/nasa-update",
            "Reuters reports on NASA and moon program",
        ),
    ]

    ranked = _filter_and_rank_results("Apollo 11 moon landing", items, 5)

    assert [item.title for item in ranked] == [
        "NASA Artemis",
        "Reuters moon mission",
    ]


def test_filter_and_rank_results_rejects_low_overlap_results():
    items = [
        _result(
            "United States of America",
            "https://uk.wikipedia.org/wiki/USA",
            "General reference page about the United States.",
            relevance=0.4,
        ),
        _result(
            "Interesting facts about USA",
            "https://example.com/usa-facts",
            "General information about the United States.",
            relevance=0.35,
        ),
    ]

    ranked = _filter_and_rank_results("USA flew to the Moon latest news", items, 5)

    assert ranked == []


@pytest.mark.asyncio
async def test_search_web_auto_uses_first_available_provider(monkeypatch):
    module = importlib.reload(web_search)
    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    monkeypatch.setenv("SEARCH_PROFILE_NEWS_ORDER", "serper,tavily")
    monkeypatch.delenv("PROVIDER_TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("PROVIDER_SERPER_API_KEY", "serper-key")
    monkeypatch.delenv("PROVIDER_BING_API_KEY", raising=False)
    monkeypatch.delenv("PROVIDER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PROVIDER_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("PROVIDER_BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("PROVIDER_PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("PROVIDER_EXA_API_KEY", raising=False)

    calls = []

    def fake_search_with_provider(
        provider,
        query,
        limit,
        recency_days,
        preferred_domains,
        preferred_domains_deny,
        profile,
        mode,
        country,
        languages,
    ):
        calls.append(
            (
                provider,
                query,
                limit,
                recency_days,
                preferred_domains,
                preferred_domains_deny,
                profile,
                mode,
                country,
                languages,
            )
        )
        if provider == "serper":
            return [
                _result(
                    "OpenAI result",
                    "https://openai.com/news",
                    "latest OpenAI news",
                    "serper",
                ),
                _result(
                    "Reuters OpenAI",
                    "https://www.reuters.com/technology/openai/",
                    "Reuters coverage of OpenAI",
                    "serper",
                ),
            ]
        return []

    async def fake_get_search_cache(*_args, **_kwargs):
        return None

    async def fake_put_search_cache(*_args, **_kwargs):
        return None

    monkeypatch.setattr(module, "_search_with_provider", fake_search_with_provider)
    monkeypatch.setattr(module, "get_search_cache", fake_get_search_cache)
    monkeypatch.setattr(module, "put_search_cache", fake_put_search_cache)

    items = await module.search_web(
        "OpenAI latest news",
        5,
        7,
        mode="news",
        profile="news",
        preferred_domains=("openai.com",),
    )

    assert [call[0] for call in calls] == ["serper"]
    assert calls[0][3] == 7
    assert calls[0][4] == ("openai.com",)
    assert calls[0][6] == "news"
    assert items[0].title == "OpenAI result"


def test_provider_order_respects_profile_override(monkeypatch):
    module = importlib.reload(web_search)
    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    monkeypatch.setenv("SEARCH_PROFILE_NEWS_ORDER", "serper,tavily,bing_html")

    assert module._provider_order("news", "news") == ["serper", "tavily", "bing_html"]


def test_provider_order_uses_profile_specific_defaults(monkeypatch):
    monkeypatch.delenv("CAPABILITY_SEARCH_WEB_PROVIDER", raising=False)
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    module = importlib.reload(web_search)

    assert module._provider_order("general", "docs")[0] == "exa_search"


def test_provider_order_uses_short_primary_fallback_defaults(monkeypatch):
    monkeypatch.delenv("CAPABILITY_SEARCH_WEB_PROVIDER", raising=False)
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("SEARCH_PROFILE_NEWS_ORDER", raising=False)
    module = importlib.reload(web_search)

    assert module._provider_order("news", "news") == [
        "brave_search",
        "serper",
        "openai_search",
        "gemini_search",
        "bing_html",
    ]


def test_provider_order_prefers_provider_hint(monkeypatch):
    monkeypatch.delenv("CAPABILITY_SEARCH_WEB_PROVIDER", raising=False)
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("SEARCH_PROFILE_DOCS_ORDER", raising=False)
    module = importlib.reload(web_search)

    assert module._provider_order("general", "docs", provider_hint="brave") == [
        "brave_search",
        "tavily",
        "openai_search",
        "bing_html",
    ]


@pytest.mark.asyncio
async def test_search_web_skips_unavailable_providers_and_continues(monkeypatch):
    module = importlib.reload(web_search)
    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    monkeypatch.delenv("SEARCH_PROFILE_NEWS_ORDER", raising=False)
    monkeypatch.delenv("PROVIDER_BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("PROVIDER_SERPER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("PROVIDER_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    calls = []

    def fake_search_with_provider(
        provider,
        query,
        limit,
        recency_days,
        preferred_domains,
        preferred_domains_deny,
        profile,
        mode,
        country,
        languages,
    ):
        calls.append(provider)
        return [
            _result(
                "NASA Artemis update",
                "https://www.nasa.gov/news/artemis-update",
                "Latest NASA Moon mission update",
                provider,
            ),
            _result(
                "AP NASA update",
                "https://apnews.com/article/nasa-moon-update",
                "AP reports on a fresh Moon mission update",
                provider,
            ),
        ]

    async def fake_get_search_cache(*_args, **_kwargs):
        return None

    async def fake_put_search_cache(*_args, **_kwargs):
        return None

    monkeypatch.setattr(module, "_search_with_provider", fake_search_with_provider)
    monkeypatch.setattr(module, "get_search_cache", fake_get_search_cache)
    monkeypatch.setattr(module, "put_search_cache", fake_put_search_cache)

    items = await module.search_web(
        "NASA Moon mission latest news",
        5,
        7,
        mode="news",
        profile="news",
    )

    assert calls == ["openai_search"]
    assert len(items) == 2


def test_gemini_grounding_items_extracts_web_chunks():
    payload = {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": "answer"}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {
                            "web": {
                                "uri": "https://openai.com/index/introducing-gpt-5/",
                                "title": "Introducing GPT-5",
                            }
                        },
                        {
                            "web": {
                                "uri": "https://www.reuters.com/technology/openai-update/",
                                "title": "Reuters OpenAI",
                            }
                        },
                    ],
                    "groundingSupports": [
                        {
                            "segment": {"text": "OpenAI announced GPT-5."},
                            "groundingChunkIndices": [0],
                        },
                        {
                            "segment": {"text": "Reuters covered the launch."},
                            "groundingChunkIndices": [1],
                        },
                    ],
                },
            }
        ]
    }

    items = web_search._gemini_grounding_items(payload)

    assert items == [
        {
            "title": "Introducing GPT-5",
            "url": "https://openai.com/index/introducing-gpt-5/",
            "snippet": "OpenAI announced GPT-5.",
            "provider": "gemini_search",
        },
        {
            "title": "Reuters OpenAI",
            "url": "https://www.reuters.com/technology/openai-update/",
            "snippet": "Reuters covered the launch.",
            "provider": "gemini_search",
        },
    ]


def test_openai_output_text_collects_message_parts():
    payload = {
        "output": [
            {"type": "reasoning"},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Line one."},
                    {"type": "output_text", "text": "Line two."},
                ],
            },
        ]
    }

    assert web_search._openai_output_text(payload) == "Line one.\nLine two."
