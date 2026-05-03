from __future__ import annotations

import base64
import logging
import os
import re
import time
import urllib.parse
from typing import Dict, Iterable, List, Optional

import requests

from agent.search_task import NormalizedResult
from core.env import (
    GEMINI_DEFAULT_BASE_URL,
    OPENAI_DEFAULT_BASE_URL,
    gemini_thinking_budget,
)
from db.search_repository import get_search_cache, put_search_cache

MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
TTL_MIN = int(os.getenv("SEARCH_CACHE_TTL_MIN", os.getenv("SEARCH_TTL_MIN", "60")))

HEADERS = {"User-Agent": "AISUSBot/1.0 (+https://example.local)"}
logger = logging.getLogger(__name__)
_search_log = logging.getLogger("smartest.search.cost")

BLOCKED_RESULT_DOMAINS = {
    "answers.microsoft.com",
    "bing.com",
    "duckduckgo.com",
    "facebook.com",
    "google.com",
    "instagram.com",
    "m.facebook.com",
    "m.zhihu.com",
    "pinterest.com",
    "quora.com",
    "twitter.com",
    "x.com",
    "zhihu.com",
}

PREFERRED_DOMAIN_SUFFIXES = (".gov", ".edu")
PREFERRED_DOMAINS = {
    "ai.google.dev",
    "anthropic.com",
    "apnews.com",
    "bbc.com",
    "developers.openai.com",
    "nasa.gov",
    "openai.com",
    "reuters.com",
    "wikipedia.org",
}

LOW_SIGNAL_MARKERS = {
    "sign in",
    "login",
    "register",
    "search results",
    "image results",
}

PROFILE_PRIMARY_PROVIDER = {
    "general": "brave_search",
    "news": "brave_search",
    "docs": "exa_search",
    "research_paper": "exa_search",
    "site_search": "tavily",
}

PROFILE_FALLBACK_CANDIDATES = {
    "general": ("serper", "openai_search", "gemini_search", "bing_html"),
    "news": ("serper", "openai_search", "gemini_search", "bing_html"),
    "docs": ("tavily", "openai_search", "bing_html"),
    "research_paper": ("tavily", "openai_search", "bing_html"),
    "site_search": ("brave_search", "openai_search", "bing_html"),
}

PROVIDER_TIMEOUTS = {
    "brave_search": 8.0,
    "serper": 5.0,
    "exa_search": 8.0,
    "tavily": 12.0,
    "tavily_extract": 12.0,
    "perplexity_search": 20.0,
    "openai_search": 15.0,
    "gemini_search": 15.0,
    "bing": 8.0,
    "bing_html": 10.0,
    "ddg": 10.0,
}

PROVIDER_NAME_ALIASES = {
    "brave": "brave_search",
    "exa": "exa_search",
    "gemini": "gemini_search",
    "openai": "openai_search",
    "perplexity": "perplexity_search",
}


def _query_prefers_latin_market(query: str) -> bool:
    latin = len(re.findall(r"[A-Za-z]", query or ""))
    cyrillic = len(re.findall(r"[А-Яа-яІіЇїЄєҐґ]", query or ""))
    return latin > cyrillic


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return str(value).strip()
    return default


def _env_csv(*names: str, default: str = "") -> list[str]:
    raw = _env_first(*names, default=default)
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _provider_api_key(provider: str) -> str:
    upper = provider.upper()
    aliases = [f"PROVIDER_{upper}_API_KEY", f"{upper}_API_KEY"]
    if provider == "gemini":
        aliases.append("GEMINI_API_KEY")
    if provider == "openai":
        aliases.extend(["OPENAI_API_KEY", "OPENAI_APIKEY", "OPENAI_API_KEY_V1"])
    return _env_first(*aliases, default="")


def _provider_base_url(provider: str, default: str = "") -> str:
    upper = provider.upper()
    aliases = [f"PROVIDER_{upper}_BASE_URL", f"{upper}_BASE_URL"]
    if provider == "openai":
        aliases.extend(["OPENAI_BASE_URL"])
    return _env_first(*aliases, default=default)


def _search_profile(mode: str, profile: str | None) -> str:
    normalized = (profile or "").strip().lower()
    if normalized in PROFILE_PRIMARY_PROVIDER:
        return normalized
    fallback = (mode or "general").strip().lower()
    return fallback if fallback in PROFILE_PRIMARY_PROVIDER else "general"


def _normalize_provider_name(provider: str | None) -> str:
    normalized = (provider or "").strip().lower()
    return PROVIDER_NAME_ALIASES.get(normalized, normalized)


def _provider_timeout(provider: str) -> float:
    return PROVIDER_TIMEOUTS.get(provider, 12.0)


def _provider_order(
    mode: str,
    profile: str | None = None,
    *,
    provider_hint: str | None = None,
) -> list[str]:
    explicit = (
        _env_first(
            "CAPABILITY_SEARCH_WEB_PROVIDER",
            "SEARCH_PROVIDER",
            default="auto",
        )
        .strip()
        .lower()
    )
    if explicit and explicit != "auto":
        return [_normalize_provider_name(explicit)]

    normalized_profile = _search_profile(mode, profile)
    env_key = f"SEARCH_PROFILE_{normalized_profile.upper()}_ORDER"
    legacy_mode_key = (
        "SEARCH_PROVIDER_ORDER_NEWS"
        if normalized_profile == "news"
        else "SEARCH_PROVIDER_ORDER"
    )
    configured = _env_csv(
        env_key,
        legacy_mode_key,
        default="",
    )
    normalized_hint = _normalize_provider_name(provider_hint)
    if configured:
        providers = []
        if normalized_hint:
            providers.append(normalized_hint)
        providers.extend(_normalize_provider_name(provider) for provider in configured)
        ordered: list[str] = []
        for provider in providers:
            if provider and provider not in ordered:
                ordered.append(provider)
        return ordered

    primary = normalized_hint or PROFILE_PRIMARY_PROVIDER[normalized_profile]
    providers = [primary]
    for provider in PROFILE_FALLBACK_CANDIDATES.get(normalized_profile, ()):
        normalized_provider = _normalize_provider_name(provider)
        if normalized_provider and normalized_provider not in providers:
            providers.append(normalized_provider)
    return providers


def _provider_is_available(provider: str) -> bool:
    if provider == "tavily":
        return bool(_provider_api_key("tavily"))
    if provider == "serper":
        return bool(_provider_api_key("serper"))
    if provider == "bing":
        return bool(_provider_api_key("bing"))
    if provider == "gemini_search":
        return bool(_provider_api_key("gemini"))
    if provider == "perplexity_search":
        return bool(_provider_api_key("perplexity"))
    if provider == "exa_search":
        return bool(_provider_api_key("exa"))
    if provider == "brave_search":
        return bool(_provider_api_key("brave"))
    if provider == "openai_search":
        base_url = _provider_base_url("openai", default=OPENAI_DEFAULT_BASE_URL)
        return bool(_provider_api_key("openai")) and "openai.com" in base_url
    if provider in {"bing_html", "ddg"}:
        return True
    return False


def _provider_cache_key(provider: str) -> str:
    return f"{provider}:v4"


def normalize_cache_query(query: str) -> str:
    raw = str(query or "").strip().lower()
    words = re.sub(r"[^\w\s]", " ", raw, flags=re.U).split()
    unique_words = sorted(set(word for word in words if word))
    normalized = " ".join(unique_words).strip()
    if normalized:
        return normalized
    return re.sub(r"\s+", " ", raw).strip()


def _search_cache_query(
    query: str,
    mode: str,
    profile: str,
    recency_days: Optional[int],
    preferred_domains_allow: tuple[str, ...],
    preferred_domains_deny: tuple[str, ...],
    country: str | None,
    languages: tuple[str, ...],
) -> str:
    normalized_profile = (profile or "general").strip().lower() or "general"
    normalized_query = normalize_cache_query(query)
    allow = ",".join(sorted(preferred_domains_allow))
    deny = ",".join(sorted(preferred_domains_deny))
    langs = ",".join(languages)
    return (
        f"v4|{normalized_profile}|{normalized_query}"
        f"|recency={recency_days or ''}"
        f"|allow={allow}"
        f"|deny={deny}"
        f"|country={(country or '').upper()}"
        f"|lang={langs}"
    )


def _domain_matches(candidate: str, patterns: tuple[str, ...]) -> bool:
    lowered = (candidate or "").lower()
    return any(
        lowered == pattern
        or lowered.endswith(f".{pattern}")
        or (pattern.startswith(".") and lowered.endswith(pattern))
        for pattern in patterns
    )


def _decode_bing_redirect(url: str) -> str:
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc.endswith("bing.com") or parsed.path != "/ck/a":
        return url

    token = (urllib.parse.parse_qs(parsed.query).get("u") or [""])[0]
    if not token.startswith("a1"):
        return url

    raw = token[2:]
    raw += "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
    except Exception:
        return url
    return decoded if decoded.startswith("http") else url


def _normalized_domain(url: str) -> str:
    netloc = urllib.parse.urlparse(url or "").netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def _normalized_url(url: str) -> str:
    parsed = urllib.parse.urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    filtered_query = [
        (key, value)
        for key, value in query
        if not key.lower().startswith(("utm_", "fbclid", "gclid", "msclkid"))
    ]
    cleaned = parsed._replace(
        fragment="",
        query=urllib.parse.urlencode(filtered_query, doseq=True),
    )
    return urllib.parse.urlunparse(cleaned)


def _title_from_url(url: str) -> str:
    domain = _normalized_domain(url)
    if not domain:
        return "Результат пошуку"
    return domain


def _query_terms(query: str) -> list[str]:
    terms = []
    for term in re.findall(r"[\w-]+", urllib.parse.unquote_plus(query or "").lower()):
        cleaned = "".join(ch for ch in term if ch.isalnum() or ch in {"-", "_"})
        if len(cleaned) < 3:
            continue
        if cleaned in {
            "the",
            "and",
            "для",
            "про",
            "що",
            "новини",
            "latest",
            "fact",
            "check",
            "today",
        }:
            continue
        terms.append(cleaned)
    return terms


LOW_VALUE_QUERY_TERMS = {
    "актуально",
    "актуальні",
    "буде",
    "вівторок",
    "вівторка",
    "для",
    "зараз",
    "найкраще",
    "новини",
    "опади",
    "погода",
    "погоди",
    "прогноз",
    "свіжі",
    "сьогодні",
    "температура",
    "this",
    "today",
    "tomorrow",
    "latest",
    "news",
    "forecast",
    "weather",
    "best",
    "what",
    "new",
    "top",
    "site",
    "www",
    "com",
    "org",
    "net",
    "ua",
}

QUERY_TERM_ALIASES = {
    "київ": ("київ", "києві", "києва", "києву", "kyiv", "kiev"),
    "kyiv": ("київ", "києві", "києва", "києву", "kyiv", "kiev"),
    "kiev": ("київ", "києві", "києва", "києву", "kyiv", "kiev"),
}


def _required_query_terms(query: str) -> list[str]:
    required: list[str] = []
    for term in _query_terms(query):
        if term in LOW_VALUE_QUERY_TERMS:
            continue
        if term.isdigit():
            continue
        if re.fullmatch(r"\d{4}[-_]\d{2}[-_]\d{2}", term):
            continue
        if term not in required:
            required.append(term)
    return required[:8]


def _item_search_haystack(item: NormalizedResult) -> str:
    return " ".join(
        [
            item.title or "",
            item.snippet or "",
            item.domain or "",
            item.url or "",
            item.full_content or "",
        ]
    ).lower()


def _term_in_haystack(term: str, haystack: str) -> bool:
    aliases = QUERY_TERM_ALIASES.get(term, (term,))
    return any(alias in haystack for alias in aliases)


def _snippet_length_score(snippet: str) -> float:
    length = len((snippet or "").strip())
    if length >= 220:
        return 0.2
    if length >= 120:
        return 0.16
    if length >= 60:
        return 0.12
    if length >= 20:
        return 0.06
    return 0.0


def _domain_bonus(
    domain: str,
    preferred_domains_allow: tuple[str, ...] = (),
) -> float:
    if not domain:
        return 0.0
    if preferred_domains_allow and _domain_matches(domain, preferred_domains_allow):
        return 0.2
    if domain in PREFERRED_DOMAINS or domain.endswith(PREFERRED_DOMAIN_SUFFIXES):
        return 0.16
    return 0.0


def _recency_bonus(raw: Dict) -> float:
    if str(raw.get("published_at") or "").strip():
        return 0.2
    if str(raw.get("last_updated") or "").strip():
        return 0.12
    if str(raw.get("page_age") or "").strip():
        return 0.08
    return 0.0


def _compute_relevance(
    query: str,
    raw: Dict,
    preferred_domains_allow: tuple[str, ...] = (),
) -> float:
    provider_score = raw.get("score")
    if provider_score not in (None, ""):
        try:
            numeric = float(provider_score)
        except (TypeError, ValueError):
            numeric = 0.0
        return max(0.0, min(numeric, 1.0))

    title = str(raw.get("title") or "").strip()
    snippet = str(raw.get("snippet") or "").strip()
    domain = _normalized_domain(str(raw.get("url") or ""))
    if not domain or domain in BLOCKED_RESULT_DOMAINS:
        return 0.0

    terms = _query_terms(query)
    haystack = " ".join([title, snippet, domain]).lower()
    overlap = 0.0
    if terms:
        overlap = min(
            0.4,
            (sum(1 for term in terms if term in haystack) / len(terms)) * 0.4,
        )
    return round(
        min(
            1.0,
            overlap
            + _snippet_length_score(snippet)
            + _domain_bonus(domain, preferred_domains_allow)
            + _recency_bonus(raw),
        ),
        4,
    )


def _match_count(query: str, item: NormalizedResult) -> int:
    haystack = _item_search_haystack(item)
    return sum(1 for term in _query_terms(query) if _term_in_haystack(term, haystack))


def _required_match_count(query: str, item: NormalizedResult) -> int:
    haystack = _item_search_haystack(item)
    return sum(
        1 for term in _required_query_terms(query) if _term_in_haystack(term, haystack)
    )


def _minimum_required_matches(query: str) -> int:
    required = _required_query_terms(query)
    if not required:
        return 0
    if len(required) == 1:
        return 1
    if len(required) <= 3:
        return len(required)
    return max(2, min(4, (len(required) + 1) // 2))


def _normalize_result(
    query: str,
    raw: Dict,
    provider: str,
    preferred_domains_allow: tuple[str, ...] = (),
) -> NormalizedResult | None:
    url = _normalized_url(_decode_bing_redirect(str(raw.get("url") or "")))
    if not url:
        return None
    domain = _normalized_domain(url)
    if not domain or domain in BLOCKED_RESULT_DOMAINS:
        return None

    title = str(raw.get("title") or "").strip() or _title_from_url(url)
    snippet = str(raw.get("snippet") or "").strip()
    haystack = f"{title} {snippet}".lower()
    if any(marker in haystack for marker in LOW_SIGNAL_MARKERS):
        return None

    return NormalizedResult(
        url=url,
        title=title,
        snippet=snippet,
        relevance_score=_compute_relevance(
            query, {**raw, "url": url}, preferred_domains_allow
        ),
        source_provider=provider,
        published_date=(
            str(raw.get("published_at") or raw.get("last_updated") or "").strip()
            or None
        ),
        domain=domain,
        has_full_content=bool(raw.get("has_full_content")),
        full_content=(str(raw.get("full_content") or "").strip() or None),
    )


def _normalize_bing_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "bing", preferred_domains_allow)


def _normalize_serper_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "serper", preferred_domains_allow)


def _normalize_tavily_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "tavily", preferred_domains_allow)


def _normalize_gemini_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "gemini_search", preferred_domains_allow)


def _normalize_perplexity_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "perplexity_search", preferred_domains_allow)


def _normalize_openai_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "openai_search", preferred_domains_allow)


def _normalize_exa_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "exa_search", preferred_domains_allow)


def _normalize_brave_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "brave_search", preferred_domains_allow)


def _normalize_bing_html_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "bing_html", preferred_domains_allow)


def _normalize_ddg_result(
    raw: Dict, query: str, preferred_domains_allow: tuple[str, ...] = ()
) -> NormalizedResult | None:
    return _normalize_result(query, raw, "ddg", preferred_domains_allow)


def _normalize_provider_item(
    raw: Dict,
    query: str,
    preferred_domains_allow: tuple[str, ...] = (),
) -> NormalizedResult | None:
    provider = str(raw.get("provider") or "").strip().lower()
    normalizers = {
        "bing": _normalize_bing_result,
        "serper": _normalize_serper_result,
        "tavily": _normalize_tavily_result,
        "gemini_search": _normalize_gemini_result,
        "perplexity_search": _normalize_perplexity_result,
        "openai_search": _normalize_openai_result,
        "exa_search": _normalize_exa_result,
        "brave_search": _normalize_brave_result,
        "bing_html": _normalize_bing_html_result,
        "ddg": _normalize_ddg_result,
    }
    normalizer = normalizers.get(provider)
    if not normalizer:
        return None
    return normalizer(raw, query, preferred_domains_allow)


def _apply_domain_filters(
    items: Iterable[NormalizedResult],
    preferred_domains_allow: tuple[str, ...],
    preferred_domains_deny: tuple[str, ...],
) -> list[NormalizedResult]:
    filtered: list[NormalizedResult] = []
    for item in items:
        domain = item.domain
        if not domain:
            continue
        if preferred_domains_allow and not _domain_matches(
            domain, preferred_domains_allow
        ):
            continue
        if preferred_domains_deny and _domain_matches(domain, preferred_domains_deny):
            continue
        filtered.append(item)
    return filtered


def _filter_and_rank_results(
    query: str,
    items: List[NormalizedResult],
    limit: int,
    preferred_domains_allow: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
) -> List[NormalizedResult]:
    prepared = []
    seen = set()
    minimum_required_matches = _minimum_required_matches(query)
    filtered_items = _apply_domain_filters(
        items,
        preferred_domains_allow,
        preferred_domains_deny,
    )
    for item in filtered_items:
        unique_key = (item.domain, item.title[:50].lower())
        if unique_key in seen:
            continue
        seen.add(unique_key)
        prepared.append(
            (
                item,
                item.relevance_score,
                _match_count(query, item),
                _required_match_count(query, item),
            )
        )

    if not prepared:
        return []

    if minimum_required_matches:
        prepared = [
            pair for pair in prepared if pair[3] >= minimum_required_matches
        ]
        if not prepared:
            return []

    sorted_items = sorted(
        prepared,
        key=lambda pair: (pair[3], pair[1], pair[2]),
        reverse=True,
    )
    ranked = [item for item, _score, _matches, _required_matches in sorted_items]

    minimum_matches = 2 if len(_query_terms(query)) >= 3 else 1
    strong = []
    for item, _score, matches, required_matches in sorted_items:
        domain = item.domain
        if minimum_required_matches and required_matches < minimum_required_matches:
            continue
        if matches >= minimum_matches:
            strong.append(item)
            continue
        if matches >= 1 and (
            domain in PREFERRED_DOMAINS
            or domain.endswith(PREFERRED_DOMAIN_SUFFIXES)
            or (
                preferred_domains_allow
                and _domain_matches(domain, preferred_domains_allow)
            )
        ):
            strong.append(item)

    if strong:
        return strong[:limit]
    if len(_query_terms(query)) >= 3:
        return []
    return ranked[:limit]


def _search_bing_html(
    query: str,
    limit: int,
    preferred_domains_allow: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
) -> List[NormalizedResult]:
    from bs4 import BeautifulSoup

    params = {"q": query}
    if _query_prefers_latin_market(query):
        params.update({"cc": "us", "setlang": "en", "mkt": "en-US"})
    else:
        params.update({"cc": "ua", "setlang": "uk", "mkt": "uk-UA"})

    resp = requests.get(
        "https://www.bing.com/search",
        headers=HEADERS,
        params=params,
        timeout=_provider_timeout("bing_html"),
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for node in soup.select("li.b_algo"):
        a = node.select_one("h2 a")
        if a is None:
            continue
        title = a.get_text(" ", strip=True)
        href = _decode_bing_redirect(a.get("href") or "")
        snippet_node = node.select_one(".b_caption p") or node.select_one(".b_snippet")
        snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
        if not href:
            continue
        items.append(
            {"title": title, "url": href, "snippet": snippet, "provider": "bing_html"}
        )
        if len(items) >= limit:
            break
    return _filter_provider_items(
        query,
        items,
        limit,
        preferred_domains_allow,
        preferred_domains_deny,
    )


def _search_ddg_html(
    query: str,
    limit: int,
    preferred_domains_allow: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
) -> List[NormalizedResult]:
    from bs4 import BeautifulSoup

    params = {"q": query}
    params["kl"] = "us-en" if _query_prefers_latin_market(query) else "ua-uk"

    resp = requests.get(
        "https://html.duckduckgo.com/html/",
        headers=HEADERS,
        params=params,
        timeout=_provider_timeout("ddg"),
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items = []
    for a in soup.select("a.result__a")[:limit]:
        title = a.get_text(" ", strip=True)
        href = a.get("href")
        snippet = ""
        sn = a.find_parent("div", class_="result__body")
        if sn:
            snt = sn.find("a", class_="result__snippet")
            snippet = snt.get_text(" ", strip=True) if snt else ""
        items.append(
            {"title": title, "url": href, "snippet": snippet, "provider": "ddg"}
        )
    return _filter_provider_items(
        query,
        items,
        limit,
        preferred_domains_allow,
        preferred_domains_deny,
    )


def _filter_provider_items(
    query: str,
    items: List[Dict],
    limit: int,
    preferred_domains_allow: tuple[str, ...],
    preferred_domains_deny: tuple[str, ...],
) -> List[NormalizedResult]:
    normalized = []
    for raw in items:
        item = _normalize_provider_item(raw, query, preferred_domains_allow)
        if item is None:
            continue
        normalized.append(item)
    return _filter_and_rank_results(
        query,
        normalized,
        limit,
        preferred_domains_allow,
        preferred_domains_deny,
    )


def _gemini_search_endpoint(model: str) -> str:
    base_url = _provider_base_url("gemini", default=GEMINI_DEFAULT_BASE_URL).rstrip("/")
    return f"{base_url}/models/{model}:generateContent"


def _gemini_grounding_items(data: Dict) -> List[Dict]:
    candidates = data.get("candidates") or []
    grounding = None
    for candidate in candidates:
        grounding = candidate.get("groundingMetadata") or candidate.get(
            "grounding_metadata"
        )
        if grounding:
            break
    if not grounding:
        return []

    snippets_by_chunk: dict[int, list[str]] = {}
    for support in grounding.get("groundingSupports", []) or grounding.get(
        "grounding_supports", []
    ):
        segment = support.get("segment") or {}
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        for index in support.get("groundingChunkIndices", []) or support.get(
            "grounding_chunk_indices", []
        ):
            snippets_by_chunk.setdefault(int(index), []).append(text)

    items: list[Dict] = []
    for index, chunk in enumerate(
        grounding.get("groundingChunks", []) or grounding.get("grounding_chunks", [])
    ):
        web = chunk.get("web") or chunk.get("webSearchResult") or {}
        url = str(web.get("uri") or web.get("url") or "").strip()
        title = str(web.get("title") or web.get("siteName") or "").strip()
        if not url:
            continue
        snippet = " ".join(dict.fromkeys(snippets_by_chunk.get(index, []))).strip()
        items.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "provider": "gemini_search",
            }
        )
    return items


def _search_gemini_grounded(
    query: str,
    limit: int,
    preferred_domains_allow: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
) -> List[Dict]:
    api_key = _provider_api_key("gemini")
    model = _env_first("SEARCH_GEMINI_MODEL", default="gemini-2.5-flash")
    preference_text = ""
    if preferred_domains_allow:
        preference_text = (
            "\nPrefer results from these domains when possible: "
            + ", ".join(preferred_domains_allow[:10])
        )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Use Google Search grounding. "
                            "Find reliable web sources for this query and answer briefly."
                            f"{preference_text}\n"
                            f"Query: {query}"
                        )
                    }
                ],
            }
        ],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 256,
        },
    }
    thinking_budget = gemini_thinking_budget(model)
    if thinking_budget is not None:
        payload["generationConfig"]["thinkingConfig"] = {
            "thinkingBudget": thinking_budget
        }

    resp = requests.post(
        _gemini_search_endpoint(model),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
            **HEADERS,
        },
        json=payload,
        timeout=_provider_timeout("gemini_search"),
    )
    resp.raise_for_status()
    data = resp.json()
    items = _gemini_grounding_items(data)
    return _filter_provider_items(
        query,
        items,
        limit,
        preferred_domains_allow,
        preferred_domains_deny,
    )


def _perplexity_recency_filter(recency_days: Optional[int]) -> str | None:
    if not recency_days:
        return None
    if recency_days <= 1:
        return "day"
    if recency_days <= 7:
        return "week"
    if recency_days <= 31:
        return "month"
    return "year"


def _openai_output_text(data: Dict) -> str:
    blocks = []
    for item in data.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text":
                text = str(part.get("text") or "").strip()
                if text:
                    blocks.append(text)
    return "\n".join(blocks).strip()


def _search_openai_grounded(
    query: str,
    limit: int,
    preferred_domains_allow: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
    country: str | None = None,
) -> List[NormalizedResult]:
    base_url = _provider_base_url("openai", default=OPENAI_DEFAULT_BASE_URL).rstrip("/")
    model = _env_first("SEARCH_OPENAI_MODEL", default="gpt-5")
    tool: Dict[str, object] = {"type": "web_search"}
    if preferred_domains_allow:
        tool["filters"] = {
            "allowed_domains": list(preferred_domains_allow[:20]),
        }
    if country:
        tool["user_location"] = {"type": "approximate", "country": country}
    payload = {
        "model": model,
        "reasoning": {"effort": "low"},
        "tools": [tool],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
        "input": query,
    }
    resp = requests.post(
        f"{base_url}/responses",
        headers={
            "Authorization": f"Bearer {_provider_api_key('openai')}",
            "Content-Type": "application/json",
            **HEADERS,
        },
        json=payload,
        timeout=_provider_timeout("openai_search"),
    )
    resp.raise_for_status()
    data = resp.json()
    summary = _openai_output_text(data)
    items: list[Dict] = []
    for output in data.get("output", []) or []:
        if output.get("type") != "web_search_call":
            continue
        action = output.get("action") or {}
        for source in action.get("sources", []) or []:
            if source.get("type") != "url":
                continue
            url = str(source.get("url") or "").strip()
            if not url:
                continue
            items.append(
                {
                    "title": _title_from_url(url),
                    "url": url,
                    "snippet": summary[:900],
                    "provider": "openai_search",
                }
            )
    return _filter_provider_items(
        query,
        items,
        limit,
        preferred_domains_allow,
        preferred_domains_deny,
    )


def _search_perplexity(
    query: str,
    limit: int,
    recency_days: Optional[int],
    preferred_domains_allow: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
    country: str | None = None,
    languages: tuple[str, ...] = (),
) -> List[NormalizedResult]:
    body: Dict[str, object] = {
        "query": query,
        "max_results": limit,
        "max_tokens_per_page": int(
            _env_first("SEARCH_PERPLEXITY_MAX_TOKENS_PER_PAGE", default="2048")
        ),
        "max_tokens": int(_env_first("SEARCH_PERPLEXITY_MAX_TOKENS", default="12000")),
    }
    recency = _perplexity_recency_filter(recency_days)
    if recency:
        body["search_recency_filter"] = recency
    if preferred_domains_allow:
        body["search_domain_filter"] = list(preferred_domains_allow[:20])
    elif preferred_domains_deny:
        body["search_domain_filter"] = [
            f"-{item}" for item in preferred_domains_deny[:20]
        ]
    if country:
        body["country"] = country
    if languages:
        body["search_language_filter"] = list(languages[:10])

    resp = requests.post(
        "https://api.perplexity.ai/search",
        headers={
            "Authorization": f"Bearer {_provider_api_key('perplexity')}",
            "Content-Type": "application/json",
            **HEADERS,
        },
        json=body,
        timeout=_provider_timeout("perplexity_search"),
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or []
    if results and isinstance(results[0], list):
        results = [item for group in results for item in group]

    items = []
    for result in results[:limit]:
        items.append(
            {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "snippet": result.get("snippet", ""),
                "published_at": result.get("date", ""),
                "last_updated": result.get("last_updated", ""),
                "provider": "perplexity_search",
            }
        )
    return _filter_provider_items(
        query,
        items,
        limit,
        preferred_domains_allow,
        preferred_domains_deny,
    )


def _search_brave(
    query: str,
    limit: int,
    recency_days: Optional[int],
    preferred_domains_allow: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
    country: str | None = None,
    languages: tuple[str, ...] = (),
) -> List[NormalizedResult]:
    params: Dict[str, object] = {
        "q": query,
        "count": min(limit, 20),
        "extra_snippets": "true",
    }
    if recency_days:
        params["freshness"] = (
            "pd" if recency_days <= 1 else "pw" if recency_days <= 7 else "pm"
        )
    if country:
        params["country"] = country
    if languages:
        params["search_lang"] = languages[0]
        params["ui_lang"] = f"{languages[0]}-{country or 'US'}"

    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={
            "X-Subscription-Token": _provider_api_key("brave"),
            **HEADERS,
        },
        params=params,
        timeout=_provider_timeout("brave_search"),
    )
    resp.raise_for_status()
    data = resp.json()
    items = []
    for result in ((data.get("web") or {}).get("results") or [])[:limit]:
        snippets = [result.get("description", "")]
        snippets.extend(result.get("extra_snippets") or [])
        items.append(
            {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "snippet": " ".join(part.strip() for part in snippets if part).strip(),
                "page_age": result.get("page_age", ""),
                "provider": "brave_search",
            }
        )
    return _filter_provider_items(
        query,
        items,
        limit,
        preferred_domains_allow,
        preferred_domains_deny,
    )


def _exa_profile_type(profile: str) -> str:
    if profile in {"research_paper", "docs"}:
        return "deep"
    return "auto"


def _exa_profile_category(profile: str) -> str | None:
    if profile == "research_paper":
        return "research paper"
    if profile == "news":
        return "news"
    return None


def _search_exa(
    query: str,
    limit: int,
    recency_days: Optional[int],
    profile: str,
    preferred_domains_allow: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
    country: str | None = None,
) -> List[NormalizedResult]:
    body: Dict[str, object] = {
        "query": query,
        "numResults": min(limit, 10),
        "type": _exa_profile_type(profile),
    }
    category = _exa_profile_category(profile)
    if category:
        body["category"] = category
    if preferred_domains_allow:
        body["includeDomains"] = list(preferred_domains_allow[:50])
    if preferred_domains_deny:
        body["excludeDomains"] = list(preferred_domains_deny[:50])
    if country:
        body["userLocation"] = country
    if recency_days:
        body["startPublishedDate"] = _start_date_iso(recency_days)

    resp = requests.post(
        "https://api.exa.ai/search",
        headers={
            "x-api-key": _provider_api_key("exa"),
            "Content-Type": "application/json",
            **HEADERS,
        },
        json=body,
        timeout=_provider_timeout("exa_search"),
    )
    resp.raise_for_status()
    data = resp.json()
    items = []
    for result in (data.get("results") or [])[:limit]:
        snippet_parts = [
            str(result.get("summary") or "").strip(),
            " ".join(result.get("highlights") or []),
            str(result.get("text") or "")[:1200].strip(),
        ]
        items.append(
            {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "snippet": " ".join(part for part in snippet_parts if part).strip(),
                "published_at": result.get("publishedDate", ""),
                "provider": "exa_search",
            }
        )
    return _filter_provider_items(
        query,
        items,
        limit,
        preferred_domains_allow,
        preferred_domains_deny,
    )


def _start_date_iso(recency_days: int) -> str:
    from datetime import datetime, timedelta, timezone

    start = datetime.now(timezone.utc) - timedelta(days=recency_days)
    return start.isoformat().replace("+00:00", "Z")


def _tavily_topic(profile: str, mode: str) -> str:
    if profile == "news" or mode == "news":
        return "news"
    return "general"


def _search_tavily(
    query: str,
    limit: int,
    recency_days: Optional[int],
    profile: str,
    mode: str,
    preferred_domains_allow: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
) -> List[NormalizedResult]:
    body: Dict[str, object] = {
        "query": query,
        "max_results": limit,
        "topic": _tavily_topic(profile, mode),
        "search_depth": "advanced"
        if profile in {"docs", "research_paper"}
        else "basic",
    }
    if preferred_domains_allow:
        body["include_domains"] = list(preferred_domains_allow[:20])
    if preferred_domains_deny:
        body["exclude_domains"] = list(preferred_domains_deny[:20])
    if recency_days:
        body["days"] = recency_days
    resp = requests.post(
        "https://api.tavily.com/search",
        headers={
            "Authorization": f"Bearer {_provider_api_key('tavily')}",
            "Content-Type": "application/json",
            **HEADERS,
        },
        json=body,
        timeout=_provider_timeout("tavily"),
    )
    resp.raise_for_status()
    data = resp.json()
    items = []
    for result in (data.get("results") or [])[:limit]:
        items.append(
            {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "snippet": result.get("content", "") or result.get("raw_content", ""),
                "score": result.get("score", 0.0),
                "provider": "tavily",
            }
        )
    return _filter_provider_items(
        query,
        items,
        limit,
        preferred_domains_allow,
        preferred_domains_deny,
    )


def _search_with_provider(
    provider: str,
    query: str,
    limit: int,
    recency_days: Optional[int],
    preferred_domains_allow: tuple[str, ...],
    preferred_domains_deny: tuple[str, ...],
    profile: str,
    mode: str,
    country: str | None,
    languages: tuple[str, ...],
) -> List[NormalizedResult]:
    if provider == "bing" and _provider_api_key("bing"):
        url = "https://api.bing.microsoft.com/v7.0/search"
        params = {
            "q": query,
            "count": limit,
            "textDecorations": False,
            "textFormat": "Raw",
        }
        if recency_days:
            params["freshness"] = (
                "Day" if recency_days <= 1 else "Week" if recency_days <= 7 else "Month"
            )
        resp = requests.get(
            url,
            headers={
                "Ocp-Apim-Subscription-Key": _provider_api_key("bing"),
                **HEADERS,
            },
            params=params,
            timeout=_provider_timeout("bing"),
        )
        resp.raise_for_status()
        data = resp.json()
        items = []
        for it in (data.get("webPages", {}) or {}).get("value", [])[:limit]:
            items.append(
                {
                    "title": it.get("name", ""),
                    "url": it.get("url", ""),
                    "snippet": it.get("snippet", ""),
                    "provider": "bing",
                }
            )
        return _filter_provider_items(
            query,
            items,
            limit,
            preferred_domains_allow,
            preferred_domains_deny,
        )

    if provider == "serper" and _provider_api_key("serper"):
        url = "https://google.serper.dev/search"
        body = {"q": query, "num": limit}
        if recency_days:
            body["tbs"] = (
                f"qdr:{'d' if recency_days <= 1 else 'w' if recency_days <= 7 else 'm'}"
            )
        resp = requests.post(
            url,
            headers={
                "X-API-KEY": _provider_api_key("serper"),
                "Content-Type": "application/json",
                **HEADERS,
            },
            json=body,
            timeout=_provider_timeout("serper"),
        )
        resp.raise_for_status()
        data = resp.json()
        items = []
        for it in (data.get("organic", []) or [])[:limit]:
            items.append(
                {
                    "title": it.get("title", ""),
                    "url": it.get("link", ""),
                    "snippet": it.get("snippet", ""),
                    "provider": "serper",
                }
            )
        return _filter_provider_items(
            query,
            items,
            limit,
            preferred_domains_allow,
            preferred_domains_deny,
        )

    if provider == "tavily" and _provider_api_key("tavily"):
        return _search_tavily(
            query,
            limit,
            recency_days,
            profile,
            mode,
            preferred_domains_allow,
            preferred_domains_deny,
        )

    if provider == "gemini_search" and _provider_api_key("gemini"):
        return _search_gemini_grounded(
            query,
            limit,
            preferred_domains_allow,
            preferred_domains_deny,
        )

    if provider == "perplexity_search" and _provider_api_key("perplexity"):
        return _search_perplexity(
            query,
            limit,
            recency_days,
            preferred_domains_allow,
            preferred_domains_deny,
            country,
            languages,
        )

    if provider == "openai_search" and _provider_is_available("openai_search"):
        return _search_openai_grounded(
            query,
            limit,
            preferred_domains_allow,
            preferred_domains_deny,
            country,
        )

    if provider == "exa_search" and _provider_api_key("exa"):
        return _search_exa(
            query,
            limit,
            recency_days,
            profile,
            preferred_domains_allow,
            preferred_domains_deny,
            country,
        )

    if provider == "brave_search" and _provider_api_key("brave"):
        return _search_brave(
            query,
            limit,
            recency_days,
            preferred_domains_allow,
            preferred_domains_deny,
            country,
            languages,
        )

    if provider == "bing_html":
        return _search_bing_html(
            query,
            limit,
            preferred_domains_allow,
            preferred_domains_deny,
        )
    if provider == "ddg":
        return _search_ddg_html(
            query,
            limit,
            preferred_domains_allow,
            preferred_domains_deny,
        )
    return []


def _extract_with_tavily(
    query: str,
    urls: list[str],
    max_chars: int,
) -> list[dict]:
    if not urls or not _provider_api_key("tavily"):
        return []
    body: Dict[str, object] = {
        "urls": urls,
        "query": query,
        "chunks_per_source": 3,
        "extract_depth": "advanced",
    }
    resp = requests.post(
        "https://api.tavily.com/extract",
        headers={
            "Authorization": f"Bearer {_provider_api_key('tavily')}",
            "Content-Type": "application/json",
            **HEADERS,
        },
        json=body,
        timeout=_provider_timeout("tavily_extract"),
    )
    resp.raise_for_status()
    data = resp.json()
    pages = []
    for result in data.get("results", []) or []:
        url = str(result.get("url") or "").strip()
        raw = str(result.get("raw_content") or "").strip()
        if not url or not raw:
            continue
        pages.append(
            {
                "title": _title_from_url(url),
                "url": url,
                "text": raw[:max_chars],
                "provider": "tavily_extract",
            }
        )
    return pages


async def extract_search_pages(
    query: str,
    results: list[NormalizedResult],
    *,
    max_pages: int,
    max_chars: int,
    profile: str = "general",
    need_primary_source: bool = False,
) -> list[NormalizedResult]:
    from agent.tools.fetch_page import fetch_page

    urls: list[str] = []
    preferred_urls: list[str] = []
    result_by_url = {result.url: result for result in results if result.url}
    for result in results:
        url = result.url.strip()
        if not url:
            continue
        domain = result.domain or _normalized_domain(url)
        if domain in PREFERRED_DOMAINS or domain.endswith(PREFERRED_DOMAIN_SUFFIXES):
            preferred_urls.append(url)
        else:
            urls.append(url)
    ordered_urls = preferred_urls + urls
    deduped_urls: list[str] = []
    seen = set()
    for url in ordered_urls:
        normalized = _normalized_url(url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped_urls.append(normalized)

    if need_primary_source and preferred_urls:
        candidate_urls = deduped_urls[: max(max_pages, 1)]
    else:
        candidate_urls = deduped_urls[:max_pages]

    page_map: dict[str, NormalizedResult] = {}
    if candidate_urls and _provider_api_key("tavily"):
        try:
            for page in _extract_with_tavily(query, candidate_urls, max_chars):
                url = _normalized_url(str(page.get("url") or ""))
                if not url:
                    continue
                match = result_by_url.get(url)
                if match is None:
                    match = NormalizedResult.from_dict(
                        {
                            "url": url,
                            "title": page.get("title") or _title_from_url(url),
                            "snippet": "",
                            "relevance_score": 0.0,
                            "source_provider": page.get("provider") or "tavily_extract",
                        }
                    )
                page_map[url] = match.with_full_content(
                    str(page.get("text") or "")[:max_chars]
                )
        except Exception as exc:
            logger.warning("search.extract_failed provider=tavily error=%s", exc)

    have_urls = set(page_map)
    for url in candidate_urls:
        if url in have_urls:
            continue
        try:
            page_text = await fetch_page(url)
        except Exception as exc:
            logger.warning("search.fetch_failed url=%s error=%s", url, exc)
            continue
        if not page_text:
            continue
        match = result_by_url.get(url)
        if match is None:
            match = NormalizedResult.from_dict(
                {
                    "url": url,
                    "title": _title_from_url(url),
                    "snippet": "",
                    "relevance_score": 0.0,
                    "source_provider": "fetch_page",
                }
            )
        page_map[url] = match.with_full_content(page_text[:max_chars])
        if len(page_map) >= max_pages:
            break

    pages = list(page_map.values())[:max_pages]
    if profile in {"docs", "research_paper"} and not pages:
        logger.info("search.extract_empty profile=%s query=%s", profile, query[:200])
    return pages


async def search_web(
    query: str,
    max_results: Optional[int] = None,
    recency_days: Optional[int] = None,
    *,
    mode: str = "general",
    profile: str | None = None,
    preferred_domains: tuple[str, ...] = (),
    preferred_domains_deny: tuple[str, ...] = (),
    country: str | None = None,
    languages: tuple[str, ...] = (),
    provider_hint: str | None = None,
) -> List[NormalizedResult]:
    limit = min(max_results or MAX_RESULTS, 10)
    normalized_profile = _search_profile(mode, profile)
    best_items: List[NormalizedResult] = []
    best_provider = ""
    minimum_acceptable = min(2, limit)
    attempted_providers = 0
    max_attempted_providers = int(
        os.getenv("SEARCH_PROVIDER_ATTEMPT_LIMIT", "2") or "2"
    )

    for provider in _provider_order(
        mode,
        normalized_profile,
        provider_hint=provider_hint,
    ):
        if not _provider_is_available(provider):
            logger.info(
                "search.provider_skip provider=%s query=%s reason=unavailable",
                provider,
                query[:200],
            )
            continue

        attempted_providers += 1
        cache_provider = _provider_cache_key(provider)
        cache_query = _search_cache_query(
            query,
            mode,
            normalized_profile,
            recency_days,
            preferred_domains,
            preferred_domains_deny,
            country,
            languages,
        )
        cached = await get_search_cache(cache_provider, cache_query, TTL_MIN)
        if cached:
            items = [NormalizedResult.from_dict(item) for item in cached[:limit]]
            logger.info(
                "search.provider_cache_hit provider=%s query=%s items=%s profile=%s hint=%s",
                provider,
                query[:200],
                len(items),
                normalized_profile,
                _normalize_provider_name(provider_hint),
            )
            _search_log.info(
                "search_cache_hit provider=%s profile=%s mode=%s query=%r results=%d ttl_min=%d",
                provider,
                normalized_profile,
                mode,
                query[:200],
                len(items),
                TTL_MIN,
            )
        else:
            started_at = time.perf_counter()
            try:
                items = _search_with_provider(
                    provider,
                    query,
                    limit,
                    recency_days,
                    preferred_domains,
                    preferred_domains_deny,
                    normalized_profile,
                    mode,
                    country,
                    languages,
                )
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                logger.warning(
                    "search.provider_failed provider=%s query=%s error=%s profile=%s hint=%s",
                    provider,
                    query[:200],
                    exc,
                    normalized_profile,
                    _normalize_provider_name(provider_hint),
                )
                _search_log.info(
                    "search_api_call provider=%s profile=%s mode=%s query=%r results=%d latency_ms=%d error=%s",
                    provider,
                    normalized_profile,
                    mode,
                    query[:200],
                    0,
                    elapsed_ms,
                    exc.__class__.__name__,
                )
                continue
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            await put_search_cache(
                cache_provider,
                cache_query,
                [item.to_dict() for item in items],
            )
            logger.info(
                "search.provider_results provider=%s query=%s items=%s profile=%s hint=%s",
                provider,
                query[:200],
                len(items),
                normalized_profile,
                _normalize_provider_name(provider_hint),
            )
            _search_log.info(
                "search_api_call provider=%s profile=%s mode=%s query=%r results=%d latency_ms=%d error=%s",
                provider,
                normalized_profile,
                mode,
                query[:200],
                len(items),
                elapsed_ms,
                "",
            )

        if len(items) > len(best_items):
            best_items = items
            best_provider = provider
        if len(items) >= minimum_acceptable:
            logger.info(
                "search.provider_selected provider=%s query=%s items=%s profile=%s mode=%s hint=%s",
                provider,
                query[:200],
                len(items),
                normalized_profile,
                mode,
                _normalize_provider_name(provider_hint),
            )
            return items[:limit]
        if attempted_providers >= max_attempted_providers and best_items:
            logger.warning(
                "search.provider_attempt_limit_reached query=%s attempts=%s best_provider=%s items=%s profile=%s mode=%s hint=%s",
                query[:200],
                attempted_providers,
                best_provider,
                len(best_items),
                normalized_profile,
                mode,
                _normalize_provider_name(provider_hint),
            )
            return best_items[:limit]

    if best_provider:
        logger.warning(
            "search.provider_best_effort provider=%s query=%s items=%s profile=%s mode=%s hint=%s",
            best_provider,
            query[:200],
            len(best_items),
            normalized_profile,
            mode,
            _normalize_provider_name(provider_hint),
        )
    return best_items[:limit]
