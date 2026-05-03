from __future__ import annotations

import importlib
import logging

import pytest

import agent.tools.web_search as web_search
from agent.search_task import NormalizedResult


def _result(
    title: str,
    url: str,
    snippet: str,
    provider: str = "test",
) -> NormalizedResult:
    return NormalizedResult(
        url=url,
        title=title,
        snippet=snippet,
        relevance_score=0.8,
        source_provider=provider,
        domain=web_search._normalized_domain(url),
    )


@pytest.mark.asyncio
async def test_search_web_profile_order_respects_profile(monkeypatch):
    module = importlib.reload(web_search)
    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    monkeypatch.setenv("SEARCH_PROFILE_DOCS_ORDER", "exa_search,openai_search")
    monkeypatch.setenv("PROVIDER_EXA_API_KEY", "exa-key")
    monkeypatch.delenv("PROVIDER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

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
        calls.append((provider, profile, mode, preferred_domains))
        return [
            _result(
                "OpenAI API docs",
                "https://developers.openai.com/api/docs",
                "Official API documentation",
                "exa_search",
            )
        ]

    async def fake_get_search_cache(*_args, **_kwargs):
        return None

    async def fake_put_search_cache(*_args, **_kwargs):
        return None

    monkeypatch.setattr(module, "_search_with_provider", fake_search_with_provider)
    monkeypatch.setattr(module, "get_search_cache", fake_get_search_cache)
    monkeypatch.setattr(module, "put_search_cache", fake_put_search_cache)

    items = await module.search_web(
        "OpenAI API docs",
        5,
        None,
        mode="general",
        profile="docs",
        preferred_domains=("developers.openai.com",),
    )

    assert calls == [("exa_search", "docs", "general", ("developers.openai.com",))]
    assert items[0].title == "OpenAI API docs"


@pytest.mark.asyncio
async def test_extract_search_pages_falls_back_to_fetch_page(monkeypatch):
    module = importlib.reload(web_search)
    monkeypatch.delenv("PROVIDER_TAVILY_API_KEY", raising=False)

    async def fake_fetch_page(url):
        return f"Fetched {url}"

    monkeypatch.setattr("agent.tools.fetch_page.fetch_page", fake_fetch_page)

    pages = await module.extract_search_pages(
        "Moon landing",
        [
            _result(
                "NASA",
                "https://www.nasa.gov/missions/artemis/",
                "NASA Artemis",
                "brave_search",
            )
        ],
        max_pages=1,
        max_chars=1000,
        profile="general",
        need_primary_source=True,
    )

    assert pages[0].url == "https://www.nasa.gov/missions/artemis/"
    assert "Fetched" in (pages[0].full_content or "")


def test_search_cache_query_normalizes_case_and_punctuation():
    first = web_search._search_cache_query(
        "Новини Apple!!!",
        "news",
        "news",
        None,
        (),
        (),
        None,
        (),
    )
    second = web_search._search_cache_query(
        "новини apple",
        "general",
        "news",
        7,
        ("apple.com",),
        ("example.com",),
        "UA",
        ("uk",),
    )

    assert first == "v4|news|apple новини|recency=|allow=|deny=|country=|lang="
    assert first != second
    assert "recency=7" in second
    assert "allow=apple.com" in second
    assert "deny=example.com" in second
    assert "country=UA" in second
    assert "lang=uk" in second


@pytest.mark.asyncio
async def test_search_web_logs_provider_call_latency(monkeypatch, caplog):
    module = importlib.reload(web_search)
    monkeypatch.setenv("SEARCH_PROVIDER", "auto")
    monkeypatch.setenv("SEARCH_PROFILE_GENERAL_ORDER", "serper")
    monkeypatch.setenv("PROVIDER_SERPER_API_KEY", "serper-key")

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
        return [_result("Result", "https://example.com/a", "Snippet", provider)]

    async def fake_get_search_cache(*_args, **_kwargs):
        return None

    async def fake_put_search_cache(*_args, **_kwargs):
        return None

    monkeypatch.setattr(module, "_search_with_provider", fake_search_with_provider)
    monkeypatch.setattr(module, "get_search_cache", fake_get_search_cache)
    monkeypatch.setattr(module, "put_search_cache", fake_put_search_cache)

    with caplog.at_level(logging.INFO, logger="smartest.search.cost"):
        items = await module.search_web(
            "example query", 5, None, mode="general", profile="general"
        )

    assert items[0].title == "Result"
    assert any(
        "search_api_call provider=serper" in record.message
        and "results=1" in record.message
        and "latency_ms=" in record.message
        for record in caplog.records
    )
