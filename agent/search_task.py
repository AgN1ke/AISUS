from __future__ import annotations

import datetime as _dt
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field, replace
from typing import Optional

from agent.llm import chat_once
from core.env import capability_model
from core.prompts import (
    SEARCH_COMPOSER_SYSTEM_PROMPT,
    SEARCH_EVALUATOR_SYSTEM_PROMPT,
    SEARCH_QUERY_PLANNER_PROMPT,
)
from memory import memory_manager

logger = logging.getLogger(__name__)

# Command prefixes to strip — this is command parsing, not intent detection.
SEARCH_QUERY_PREFIXES = [
    r"^/think\b",
    # Explicit search commands. Includes short forms ("гугли", "шукай") that
    # users actually type in chat — devlog Session 115: trace 257757/9 was
    # "Гугли - сбу операція павутина" — "гугли" without "за/по" prefix
    # wasn't matched, request was auto-downgraded as if there were no
    # keyword. Now "гугли" / "шукай" count as explicit triggers.
    r"^(пошукай|погугли|загугли|гугли|шукай)\b[\s:,-]*",
    r"^(знайди|перевір)\s+в\s+інтернеті\b[\s:,-]*",
]

ALLOWED_SEARCH_PROFILES = {
    "general",
    "news",
    "docs",
    "research_paper",
    "site_search",
}

WEATHER_DOMAIN_HINTS = (
    "sinoptik.ua",
    "meteofor.com.ua",
    "meteo.ua",
    "weather.com",
    "accuweather.com",
)

_WEATHER_TERMS_RE = re.compile(
    r"\b(погода|погоди|погодн\w*|прогноз|температура|опади)\b",
    flags=re.I,
)
_WEATHER_CITY_ALIASES = {
    "kyiv": (
        "київ",
        "києві",
        "києва",
        "києву",
        "киев",
        "киеве",
        "kiev",
        "kyiv",
    ),
}
_WEATHER_CITY_DISPLAY = {
    "kyiv": "Київ",
}
_WEEKDAY_FORMS = {
    "понеділок": 0,
    "понеділка": 0,
    "вівторок": 1,
    "вівторка": 1,
    "середу": 2,
    "середа": 2,
    "четвер": 3,
    "четверга": 3,
    "п'ятницю": 4,
    "пятницю": 4,
    "п'ятниця": 4,
    "пятниця": 4,
    "суботу": 5,
    "субота": 5,
    "неділю": 6,
    "неділя": 6,
}

LOW_VALUE_QUERY_TERMS = {
    "актуально",
    "актуальні",
    "буде",
    "вівторок",
    "вівторка",
    "для",
    "зараз",
    "найкраще",
    "нового",
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


@dataclass(frozen=True)
class SearchTask:
    original_request: str
    query: str
    source: str
    used_context: bool = False
    reason: str = ""
    mode: str = "general"
    recency_days: int | None = None
    preferred_domains: tuple[str, ...] = ()
    profile: str = "general"
    provider_hint: str | None = None
    alternative_queries: tuple[str, ...] = ()
    preferred_domains_deny: tuple[str, ...] = ()
    country: str | None = None
    languages: tuple[str, ...] = ()
    need_extract: bool = False
    need_primary_source: bool = False
    max_iterations: int = 3


@dataclass(frozen=True)
class SubQuery:
    query: str
    profile: str = "general"
    alternative: str | None = None
    provider_hint: str | None = None


@dataclass(frozen=True)
class SearchPlan:
    sub_queries: tuple[SubQuery, ...]
    original_request: str
    needs_extract: bool = False
    recency_days: int | None = None


@dataclass(frozen=True)
class NormalizedResult:
    url: str
    title: str
    snippet: str
    relevance_score: float
    source_provider: str
    published_date: str | None = None
    domain: str = ""
    has_full_content: bool = False
    full_content: str | None = None

    def with_full_content(self, text: str | None) -> "NormalizedResult":
        content = (text or "").strip()
        return replace(
            self,
            has_full_content=bool(content),
            full_content=content or None,
        )

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "relevance_score": self.relevance_score,
            "source_provider": self.source_provider,
            "published_date": self.published_date,
            "domain": self.domain,
            "has_full_content": self.has_full_content,
            "full_content": self.full_content,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NormalizedResult":
        url = str(data.get("url") or "").strip()
        domain = str(data.get("domain") or "").strip().lower()
        if not domain and url:
            parsed = urllib.parse.urlparse(url)
            domain = (parsed.netloc or "").lower()
            if domain.startswith("www."):
                domain = domain[4:]
        return cls(
            url=url,
            title=str(data.get("title") or "").strip(),
            snippet=str(data.get("snippet") or "").strip(),
            relevance_score=float(data.get("relevance_score") or 0.0),
            source_provider=str(
                data.get("source_provider") or data.get("provider") or ""
            ).strip(),
            published_date=(str(data.get("published_date") or "").strip() or None),
            domain=domain,
            has_full_content=bool(data.get("has_full_content")),
            full_content=(str(data.get("full_content") or "").strip() or None),
        )


@dataclass
class EvidencePack:
    results: list[NormalizedResult]
    sub_query_coverage: dict[str, bool]
    total_providers_used: int
    total_results_before_filter: int
    extraction_attempted: bool = False
    pages: list[NormalizedResult] = field(default_factory=list)
    retry_queries: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchEvaluation:
    sufficient: bool
    should_retry: bool = False
    retry_query: str = ""
    reason: str = ""
    retry_sub_query: SubQuery | None = None
    coverage: dict[str, bool] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_results(
    items: list[NormalizedResult] | list[dict] | None,
) -> list[NormalizedResult]:
    normalized: list[NormalizedResult] = []
    for item in items or []:
        if isinstance(item, NormalizedResult):
            normalized.append(item)
            continue
        if isinstance(item, dict):
            normalized.append(NormalizedResult.from_dict(item))
    return normalized


def _task_mode_for_profile(profile: str, fallback: str) -> str:
    normalized = (profile or "").strip().lower()
    if normalized in {"general", "news"}:
        return normalized
    return fallback


def _normalize_profile(profile: str | None, fallback: str = "general") -> str:
    normalized = (profile or "").strip().lower()
    if normalized in ALLOWED_SEARCH_PROFILES:
        return normalized
    return fallback


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _sanitize_query_text(text: str) -> str:
    """Minimal text cleaning: collapse spaces, remove @mentions, strip edge punctuation."""
    cleaned = _collapse_spaces(text)
    cleaned = re.sub(r"@\w+", "", cleaned)
    return cleaned.strip(" \t\r\n,.;:!?-")


def _looks_like_weather_query(text: str) -> bool:
    return bool(_WEATHER_TERMS_RE.search(text or ""))


def _weather_city_key(text: str) -> str | None:
    lowered = (text or "").lower()
    for city_key, aliases in _WEATHER_CITY_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return city_key
    return None


def _weather_city_aliases(text: str) -> tuple[str, ...]:
    city_key = _weather_city_key(text)
    if not city_key:
        return ()
    return _WEATHER_CITY_ALIASES[city_key]


def _next_weekday_iso(text: str, *, today: _dt.date | None = None) -> str:
    lowered = (text or "").lower()
    target_weekday = None
    for form, weekday in _WEEKDAY_FORMS.items():
        if form in lowered:
            target_weekday = weekday
            break
    if target_weekday is None:
        return ""
    base = today or _dt.datetime.utcnow().date()
    days_ahead = (target_weekday - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (base + _dt.timedelta(days=days_ahead)).isoformat()


def _append_unique(values: tuple[str, ...], *extra: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in (*values, *extra):
        cleaned = (value or "").strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return tuple(result)


def _weather_retry_queries(text: str, city_key: str) -> tuple[str, ...]:
    city = _WEATHER_CITY_DISPLAY.get(city_key, city_key)
    date_iso = _next_weekday_iso(text)
    date_part = f" {date_iso}" if date_iso else ""
    return (
        f"site:sinoptik.ua/pohoda/{city_key} погода {city}{date_part}".strip(),
        f"погода {city}{date_part} sinoptik.ua".strip(),
    )


def _enrich_weather_task(task: SearchTask) -> SearchTask:
    text = f"{task.original_request} {task.query}"
    if not _looks_like_weather_query(text):
        return task
    city_key = _weather_city_key(text)
    if not city_key:
        return task
    return replace(
        task,
        preferred_domains=_append_unique(task.preferred_domains, *WEATHER_DOMAIN_HINTS),
        country=task.country or "UA",
        languages=task.languages or ("uk",),
        need_extract=True,
        alternative_queries=_append_unique(
            task.alternative_queries,
            *_weather_retry_queries(text, city_key),
        ),
        reason=f"{task.reason};weather_location_guard".strip(";"),
    )


def _text_has_any_alias(text: str, aliases: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(alias in lowered for alias in aliases)


def _query_terms(text: str) -> list[str]:
    terms: list[str] = []
    for term in re.findall(r"[\w-]+", urllib.parse.unquote_plus(text or "").lower()):
        cleaned = "".join(ch for ch in term if ch.isalnum() or ch in {"-", "_"})
        if len(cleaned) >= 3:
            terms.append(cleaned)
    return terms


def _required_query_terms(text: str) -> list[str]:
    required: list[str] = []
    for term in _query_terms(text):
        if term in LOW_VALUE_QUERY_TERMS:
            continue
        if term.isdigit():
            continue
        if re.fullmatch(r"\d{4}[-_]\d{2}[-_]\d{2}", term):
            continue
        if term not in required:
            required.append(term)
    return required[:8]


def _evidence_haystack(
    results: list[NormalizedResult],
    pages: list[NormalizedResult],
) -> str:
    chunks: list[str] = []
    for item in [*results, *pages]:
        chunks.extend(
            [
                item.title or "",
                item.snippet or "",
                item.domain or "",
                item.url or "",
                item.full_content or "",
            ]
        )
    return " ".join(chunks).lower()


def _term_in_haystack(term: str, haystack: str) -> bool:
    aliases = QUERY_TERM_ALIASES.get(term, (term,))
    return any(alias in haystack for alias in aliases)


def _minimum_required_matches(text: str) -> int:
    required = _required_query_terms(text)
    if not required:
        return 0
    if len(required) == 1:
        return 1
    if len(required) <= 3:
        return len(required)
    return max(2, min(4, (len(required) + 1) // 2))


def _has_query_anchor_coverage(
    query: str,
    results: list[NormalizedResult],
    pages: list[NormalizedResult],
) -> bool:
    required = _required_query_terms(query)
    minimum = _minimum_required_matches(query)
    if not required or not minimum:
        return True
    haystack = _evidence_haystack(results, pages)
    matches = sum(1 for term in required if _term_in_haystack(term, haystack))
    return matches >= minimum


def _has_weather_location_coverage(
    original_request: str,
    query: str,
    results: list[NormalizedResult],
    pages: list[NormalizedResult],
) -> bool:
    text = f"{original_request} {query}"
    if not _looks_like_weather_query(text):
        return True
    aliases = _weather_city_aliases(text)
    if not aliases:
        return True
    for item in [*results, *pages]:
        haystack = " ".join(
            [
                item.title or "",
                item.snippet or "",
                item.domain or "",
                item.url or "",
                item.full_content or "",
            ]
        )
        if _text_has_any_alias(haystack, aliases):
            return True
    return False


def strip_search_command(user_text: str) -> str:
    text = (user_text or "").strip()
    for pattern in SEARCH_QUERY_PREFIXES:
        text = re.sub(pattern, "", text, count=1, flags=re.I).strip()
    return text


def normalize_search_query(user_text: str) -> str:
    """Strip command prefix and do minimal text cleanup.

    Slang normalisation, entity rewriting and language adaptation are
    handled by the LLM composer / planner — not by regex here.
    """
    return _sanitize_query_text(strip_search_command(user_text))


def _build_search_task(
    *,
    original_request: str,
    query: str,
    source: str,
    used_context: bool,
    reason: str,
) -> SearchTask:
    """Build a SearchTask with safe defaults.

    Profile, mode, recency and domain hints are determined later by the
    LLM planner, not by regex heuristics.
    """
    return SearchTask(
        original_request=original_request,
        query=query,
        source=source,
        used_context=used_context,
        reason=reason,
        mode="general",
        profile="general",
    )


def _is_underspecified_search_request(user_text: str) -> bool:
    text = (user_text or "").strip()
    if not text:
        return True
    stripped = strip_search_command(text)
    words = [w for w in re.findall(r"\w+", stripped.lower()) if len(w) > 2]
    return len(words) < 2


def is_explicit_search_request(user_text: str) -> bool:
    text = (user_text or "").strip()
    if not text:
        return False
    return strip_search_command(text) != text


def trim_terminal_user_duplicate(
    context_msgs: list[dict], user_text: str
) -> list[dict]:
    """Drop the last user message from context if it duplicates user_text.

    Match strategies (in priority order):
      1. Strict equality (legacy: bare user role + content).
      2. Suffix match: speaker-prefixed turns store the original text after
         `\\n\\n` (Session 105 _annotate_recent_rows). Strip that header
         and compare. Without this fix the model sees the same question
         twice — once in recent (speaker-prefixed) and once as the appended
         user_text — and hallucinates "ти двічі питаєш".
    """
    if not context_msgs:
        return []
    last = context_msgs[-1]
    if last.get("role") != "user":
        return context_msgs
    last_content = (last.get("content") or "").strip()
    target = (user_text or "").strip()
    if not target:
        return context_msgs
    if last_content == target:
        return context_msgs[:-1]
    # Speaker-prefixed: "[Speaker: ...]\n...\n\n<actual user text>"
    if "\n\n" in last_content:
        tail = last_content.split("\n\n", 1)[1].strip()
        if tail == target:
            return context_msgs[:-1]
    return context_msgs


def _context_excerpt(context_msgs: list[dict], limit: int = 6) -> str:
    relevant = []
    for msg in context_msgs:
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if role == "system" and content.startswith("[CHAT-GEOMETRY]"):
            relevant.append({"role": "system", "content": content[:800]})
            continue
        if role not in {"user", "assistant"}:
            continue
        if not content:
            continue
        if content.startswith("[LONG-MEMO]"):
            continue
        relevant.append({"role": role, "content": content[:800]})
    tail = relevant[-limit:]
    lines = []
    for item in tail:
        speaker = (
            "user"
            if item["role"] == "user"
            else "assistant"
            if item["role"] == "assistant"
            else "system"
        )
        lines.append(f"{speaker}: {item['content']}")
    return "\n".join(lines)


def _geometry_reply_text(context_msgs: list[dict]) -> str:
    for msg in reversed(context_msgs):
        content = (msg.get("content") or "").strip()
        if (msg.get("role") or "").strip().lower() != "system":
            continue
        if not content.startswith("[CHAT-GEOMETRY]"):
            continue
        match = re.search(r"^reply_target_text:\s*(.+)$", content, flags=re.M)
        if not match:
            continue
        return _sanitize_query_text(match.group(1).strip()[:240])
    return ""


def _extract_json_block(text: str) -> Optional[dict]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _heuristic_context_query(context_msgs: list[dict], user_text: str) -> str:
    """Pick the best query from context when user message is vague."""
    stripped = normalize_search_query(user_text)
    if stripped and not _is_underspecified_search_request(user_text):
        return stripped

    geometry_reply = _geometry_reply_text(context_msgs)
    if geometry_reply:
        return geometry_reply

    for msg in reversed(context_msgs):
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if content == (user_text or "").strip():
            continue
        candidate = _sanitize_query_text(content[:240])
        if len(candidate) >= 8:
            return candidate

    return stripped or (user_text or "").strip()


def _safe_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _heuristic_plan_from_task(base_task: SearchTask) -> SearchPlan:
    alternative = (
        base_task.alternative_queries[0] if base_task.alternative_queries else None
    )
    return SearchPlan(
        sub_queries=(
            SubQuery(
                query=base_task.query,
                profile=base_task.profile,
                alternative=alternative,
                provider_hint=base_task.provider_hint,
            ),
        ),
        original_request=base_task.original_request,
        needs_extract=base_task.need_extract,
        recency_days=base_task.recency_days,
    )


# ---------------------------------------------------------------------------
# LLM-backed query planner
# ---------------------------------------------------------------------------


def _plan_with_model(
    user_text: str,
    dialogue_excerpt: list[dict],
    *,
    mode_hint: str | None = None,
) -> SearchPlan | None:
    today = _dt.datetime.utcnow().date().isoformat()
    payload = {
        "today_date": today,
        "latest_user_message": (user_text or "")[:800],
        "dialogue_excerpt": _context_excerpt(dialogue_excerpt),
        "mode_hint": (mode_hint or "").strip() or None,
    }
    messages = [
        {"role": "system", "content": SEARCH_QUERY_PLANNER_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    response = chat_once(
        messages,
        tools=None,
        use_reasoning=False,
        model=capability_model("search_query_planner"),
        temperature=0,
        capability="search_query_planner",
    )
    content = response.choices[0].message.content or ""
    parsed = _extract_json_block(content)
    if not parsed:
        logger.warning("search_plan.parse_failed content=%s", content[:400])
        return None

    intent_hypothesis = str(parsed.get("intent_hypothesis") or "").strip()
    if intent_hypothesis:
        logger.info(
            "search_plan.intent_hypothesis user=%s hypothesis=%s",
            (user_text or "")[:120],
            intent_hypothesis[:240],
        )

    raw_sub_queries = parsed.get("sub_queries")
    if not isinstance(raw_sub_queries, list):
        return None

    fallback_profile = _normalize_profile(mode_hint, fallback="general")
    sub_queries: list[SubQuery] = []
    for item in raw_sub_queries[:3]:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        profile = _normalize_profile(item.get("profile"), fallback=fallback_profile)
        alternative = str(item.get("alternative") or "").strip() or None
        if alternative and alternative.lower() == query.lower():
            alternative = None
        provider_hint = str(item.get("provider_hint") or "").strip().lower() or None
        sub_queries.append(
            SubQuery(
                query=query,
                profile=profile,
                alternative=alternative,
                provider_hint=provider_hint,
            )
        )

    if not sub_queries:
        return None

    recency_days = _safe_int(parsed.get("recency_days"))
    return SearchPlan(
        sub_queries=tuple(sub_queries),
        original_request=user_text,
        needs_extract=bool(parsed.get("needs_extract")),
        recency_days=recency_days,
    )


# ---------------------------------------------------------------------------
# Search context & task building
# ---------------------------------------------------------------------------


async def _select_search_context(
    chat_id: int,
    user_text: str,
    *,
    turn_context_msgs: list[dict] | None = None,
) -> list[dict]:
    context = await memory_manager.select_context(
        chat_id=chat_id,
        user_query=user_text,
        system_prompt=None,
    )
    if turn_context_msgs:
        context = list(turn_context_msgs) + context
    return trim_terminal_user_duplicate(context, user_text)


def _build_single_search_task_from_context(
    user_text: str,
    context: list[dict],
) -> SearchTask:
    normalized_direct = normalize_search_query(user_text)
    if is_explicit_search_request(user_text):
        return _build_search_task(
            original_request=user_text,
            query=normalized_direct,
            source="direct_normalized",
            used_context=False,
            reason="explicit_search_request",
        )

    try:
        composed = _compose_with_model(user_text, context)
    except Exception as exc:
        logger.warning("search_task.llm_failed error=%s", exc)
        composed = None
    if composed:
        return composed

    fallback_query = _heuristic_context_query(context, user_text)
    return _build_search_task(
        original_request=user_text,
        query=fallback_query,
        source="heuristic_context",
        used_context=True,
        reason="fallback_contextual_query",
    )


def _tasks_from_plan(base_task: SearchTask, plan: SearchPlan) -> list[SearchTask]:
    if not plan.sub_queries:
        return [_enrich_weather_task(base_task)]

    if len(plan.sub_queries) == 1:
        only = plan.sub_queries[0]
        same_query = (
            only.query.strip().lower() == (base_task.query or "").strip().lower()
        )
        same_profile = (
            _normalize_profile(only.profile, fallback=base_task.profile)
            == base_task.profile
        )
        no_override = (
            not only.alternative
            and not only.provider_hint
            and (
                plan.recency_days is None or plan.recency_days == base_task.recency_days
            )
            and (not plan.needs_extract or base_task.need_extract)
        )
        if same_query and same_profile and no_override:
            return [_enrich_weather_task(base_task)]

    tasks: list[SearchTask] = []
    for sub_query in plan.sub_queries[:3]:
        query = sub_query.query.strip()
        if not query:
            continue
        task = _build_search_task(
            original_request=base_task.original_request,
            query=query,
            source="query_planner",
            used_context=base_task.used_context,
            reason=f"planned_subquery:{sub_query.profile}",
        )
        profile = _normalize_profile(sub_query.profile, fallback=task.profile)
        mode = _task_mode_for_profile(profile, task.mode)
        alternative = (sub_query.alternative or "").strip() or None
        alternatives = tuple(
            alt
            for alt in [alternative]
            if alt and alt.lower() != (task.query or "").lower()
        )
        task = replace(
            task,
            source="query_planner",
            used_context=base_task.used_context,
            reason=f"planned_subquery:{profile}",
            mode=mode,
            profile=profile,
            provider_hint=sub_query.provider_hint,
            alternative_queries=alternatives,
            recency_days=plan.recency_days
            if plan.recency_days is not None
            else task.recency_days,
            need_extract=bool(
                plan.needs_extract or task.need_extract or base_task.need_extract
            ),
            need_primary_source=bool(
                task.need_primary_source
                or profile in {"docs", "research_paper", "site_search"}
            ),
        )
        tasks.append(_enrich_weather_task(task))

    return tasks or [_enrich_weather_task(base_task)]


# ---------------------------------------------------------------------------
# Coverage & evaluation helpers
# ---------------------------------------------------------------------------


def has_search_coverage(
    results: list[NormalizedResult | dict] | None,
    pages: list[NormalizedResult | dict] | None,
    *,
    min_relevance: float = 0.5,
) -> bool:
    normalized_results = _normalize_results(results)
    normalized_pages = _normalize_results(pages)
    if any(
        page.has_full_content or (page.full_content or "").strip()
        for page in normalized_pages
    ):
        return True
    if any(result.relevance_score >= min_relevance for result in normalized_results):
        return True
    if normalized_results and not any(
        result.relevance_score > 0 for result in normalized_results
    ):
        distinct_domains = {
            (result.domain or "").lower() for result in normalized_results if result.url
        }
        if len(normalized_results) >= 3 and len(distinct_domains) >= 2:
            return True
    return False


def suggest_retry_query(
    original_request: str,
    query: str,
    *,
    alternatives: tuple[str, ...] = (),
) -> str:
    current = (query or "").strip().lower()
    for alternative in alternatives:
        candidate = alternative.strip()
        if candidate and candidate.lower() != current:
            return candidate
    fallback = _heuristic_retry_query(original_request, query).strip()
    if fallback and fallback.lower() != current:
        return fallback
    return ""


def _results_brief(
    results: list[NormalizedResult],
    pages: list[NormalizedResult],
    *,
    sub_queries: tuple[SubQuery, ...] = (),
    coverage: dict[str, bool] | None = None,
) -> dict:
    return {
        "sub_queries": [
            {
                "query": sub_query.query[:240],
                "profile": sub_query.profile,
                "provider_hint": sub_query.provider_hint,
                "alternative": (sub_query.alternative or "")[:240] or None,
                "covered": bool((coverage or {}).get(sub_query.query, False)),
            }
            for sub_query in sub_queries[:3]
        ],
        "results": [
            {
                "title": result.title[:200],
                "url": result.url[:400],
                "snippet": result.snippet[:800],
                "relevance_score": round(result.relevance_score, 3),
                "source_provider": result.source_provider,
            }
            for result in results[:8]
        ],
        "pages": [
            {
                "title": page.title[:200],
                "url": page.url[:400],
                "text": (page.full_content or "")[:2000],
                "source_provider": page.source_provider,
            }
            for page in pages[:3]
        ],
    }


def _heuristic_retry_query(original_request: str, query: str) -> str:
    normalized_original = normalize_search_query(original_request)
    normalized_query = normalize_search_query(query)
    base = (
        normalized_query
        or normalized_original
        or (query or original_request).strip()
    )
    if not base:
        return ""
    if normalized_original and normalized_original.lower() != base.lower():
        return normalized_original
    return base


def _heuristic_search_evaluation(
    original_request: str,
    query: str,
    results: list[NormalizedResult],
    pages: list[NormalizedResult],
) -> SearchEvaluation:
    basic_coverage = has_search_coverage(results, pages)
    anchor_coverage = _has_query_anchor_coverage(query, results, pages)
    weather_coverage = _has_weather_location_coverage(
        original_request, query, results, pages
    )
    coverage = {query: bool(basic_coverage and anchor_coverage and weather_coverage)}
    retry_query = suggest_retry_query(original_request, query)
    if basic_coverage and not anchor_coverage:
        return SearchEvaluation(
            sufficient=False,
            should_retry=bool(retry_query),
            retry_query=retry_query,
            reason="query_anchor_mismatch",
            coverage={query: False},
        )
    if basic_coverage and not weather_coverage:
        return SearchEvaluation(
            sufficient=False,
            should_retry=True,
            retry_query=retry_query,
            reason="weather_location_mismatch",
            coverage={query: False},
        )
    high_relevance = [result for result in results if result.relevance_score >= 0.5]
    distinct_domains = {
        (result.domain or "").lower() for result in results if result.url
    }

    if not results and not pages:
        return SearchEvaluation(
            sufficient=False,
            should_retry=bool(retry_query),
            retry_query=retry_query,
            reason="no_results",
            coverage=coverage,
        )

    if coverage[query] and pages:
        return SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason="page_evidence_present",
            coverage=coverage,
        )

    if len(results) >= 3 and len(distinct_domains) >= 2:
        return SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason="multiple_search_hits",
            coverage=coverage,
        )

    if len(high_relevance) >= 2:
        return SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason="high_relevance_hits",
            coverage=coverage,
        )

    return SearchEvaluation(
        sufficient=False,
        should_retry=bool(retry_query),
        retry_query=retry_query,
        reason="low_relevance_results",
        coverage=coverage,
    )


# ---------------------------------------------------------------------------
# LLM-backed composer & evaluator
# ---------------------------------------------------------------------------


def _compose_with_model(
    user_text: str, context_msgs: list[dict]
) -> Optional[SearchTask]:
    payload = {
        "latest_user_message": (user_text or "")[:800],
        "dialogue_excerpt": _context_excerpt(context_msgs),
    }
    messages = [
        {"role": "system", "content": SEARCH_COMPOSER_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    response = chat_once(
        messages,
        tools=None,
        use_reasoning=False,
        model=capability_model("search_query_composer"),
        temperature=0,
        capability="search_query_composer",
    )
    content = response.choices[0].message.content or ""
    parsed = _extract_json_block(content)
    if not parsed:
        logger.warning("search_task.parse_failed content=%s", content[:400])
        return None

    query = str(parsed.get("query") or "").strip()
    reason = str(parsed.get("reason") or "").strip()
    if not query:
        return None
    return _build_search_task(
        original_request=user_text,
        query=query,
        source="llm_composer",
        used_context=bool(parsed.get("used_context")),
        reason=reason,
    )


def _evaluate_with_model(
    original_request: str,
    query: str,
    results: list[NormalizedResult],
    pages: list[NormalizedResult],
    *,
    sub_queries: tuple[SubQuery, ...] = (),
    coverage: dict[str, bool] | None = None,
) -> Optional[SearchEvaluation]:
    payload = {
        "original_request": (original_request or "")[:800],
        "search_query": (query or "")[:400],
        **_results_brief(
            results,
            pages,
            sub_queries=sub_queries,
            coverage=coverage,
        ),
    }
    messages = [
        {"role": "system", "content": SEARCH_EVALUATOR_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    response = chat_once(
        messages,
        tools=None,
        use_reasoning=False,
        model=capability_model("search_evaluator"),
        temperature=0,
        capability="search_evaluator",
    )
    content = response.choices[0].message.content or ""
    parsed = _extract_json_block(content)
    if not parsed:
        logger.warning("search_eval.parse_failed content=%s", content[:400])
        return None

    sufficient = bool(parsed.get("sufficient"))
    retry_query = str(parsed.get("retry_query") or "").strip()
    reason = str(parsed.get("reason") or "").strip()
    raw_coverage = parsed.get("coverage")
    parsed_coverage: dict[str, bool] = {}
    if isinstance(raw_coverage, dict):
        parsed_coverage = {
            str(key).strip(): bool(value)
            for key, value in raw_coverage.items()
            if str(key).strip()
        }
    elif isinstance(raw_coverage, list):
        for item in raw_coverage:
            if not isinstance(item, dict):
                continue
            key = str(item.get("query") or item.get("sub_query") or "").strip()
            if key:
                parsed_coverage[key] = bool(item.get("covered"))

    retry_sub_query = None
    retry_sub_query_text = str(parsed.get("retry_sub_query") or "").strip().lower()
    if retry_sub_query_text:
        for sub_query in sub_queries:
            if retry_sub_query_text == sub_query.query.strip().lower():
                retry_sub_query = sub_query
                break
        if retry_sub_query is None:
            for sub_query in sub_queries:
                if retry_sub_query_text in sub_query.query.strip().lower():
                    retry_sub_query = sub_query
                    break
    if sufficient:
        retry_query = ""

    return SearchEvaluation(
        sufficient=sufficient,
        should_retry=bool(not sufficient and retry_query),
        retry_query=retry_query,
        reason=reason,
        retry_sub_query=retry_sub_query,
        coverage=parsed_coverage,
    )


def _heuristic_evidence_evaluation(
    plan: SearchPlan,
    evidence: EvidencePack,
) -> SearchEvaluation:
    anchor_mismatch: set[str] = set()
    weather_mismatch: set[str] = set()
    coverage = {
        sub_query.query: bool(
            evidence.sub_query_coverage.get(sub_query.query, False)
            and _has_query_anchor_coverage(
                sub_query.query,
                evidence.results,
                evidence.pages,
            )
            and _has_weather_location_coverage(
                plan.original_request,
                sub_query.query,
                evidence.results,
                evidence.pages,
            )
        )
        for sub_query in plan.sub_queries
    }
    for sub_query in plan.sub_queries:
        if not evidence.sub_query_coverage.get(sub_query.query, False):
            continue
        if not _has_query_anchor_coverage(
            sub_query.query,
            evidence.results,
            evidence.pages,
        ):
            anchor_mismatch.add(sub_query.query)
        if not _has_weather_location_coverage(
            plan.original_request,
            sub_query.query,
            evidence.results,
            evidence.pages,
        ):
            weather_mismatch.add(sub_query.query)
    missing = [
        sub_query for sub_query in plan.sub_queries if not coverage[sub_query.query]
    ]
    if missing:
        retry_sub_query = missing[0]
        retry_query = str(
            evidence.retry_queries.get(retry_sub_query.query) or ""
        ).strip() or suggest_retry_query(
            plan.original_request,
            retry_sub_query.query,
            alternatives=(
                (retry_sub_query.alternative,) if retry_sub_query.alternative else ()
            ),
        )
        return SearchEvaluation(
            sufficient=False,
            should_retry=bool(retry_query),
            retry_query=retry_query,
            reason=(
                "weather_location_mismatch"
                if retry_sub_query.query in weather_mismatch
                else "query_anchor_mismatch"
                if retry_sub_query.query in anchor_mismatch
                else "missing_sub_query_coverage"
            ),
            retry_sub_query=retry_sub_query,
            coverage=coverage,
        )

    high_relevance = [
        result for result in evidence.results if result.relevance_score >= 0.5
    ]
    minimum_high_relevance = max(2, len(plan.sub_queries))
    if len(high_relevance) >= minimum_high_relevance:
        return SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason="high_relevance_coverage",
            coverage=coverage,
        )
    if high_relevance and evidence.extraction_attempted and evidence.pages:
        return SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason="page_evidence_present",
            coverage=coverage,
        )
    return SearchEvaluation(
        sufficient=False,
        should_retry=False,
        retry_query="",
        reason="low_relevance_results",
        coverage=coverage,
    )


# ---------------------------------------------------------------------------
# Public evaluation API
# ---------------------------------------------------------------------------


def evaluate_evidence(
    plan: SearchPlan,
    evidence: EvidencePack,
    attempt: int,
) -> SearchEvaluation:
    normalized_results = _normalize_results(evidence.results)
    normalized_pages = _normalize_results(evidence.pages)
    normalized_evidence = EvidencePack(
        results=normalized_results,
        sub_query_coverage=dict(evidence.sub_query_coverage),
        total_providers_used=evidence.total_providers_used,
        total_results_before_filter=evidence.total_results_before_filter,
        extraction_attempted=evidence.extraction_attempted,
        pages=normalized_pages,
        retry_queries=dict(evidence.retry_queries),
    )
    heuristic = _heuristic_evidence_evaluation(plan, normalized_evidence)
    combined_query = " ; ".join(
        sub_query.query for sub_query in plan.sub_queries if sub_query.query
    )[:400]
    try:
        evaluated = _evaluate_with_model(
            plan.original_request,
            combined_query,
            normalized_results,
            normalized_pages,
            sub_queries=plan.sub_queries,
            coverage=heuristic.coverage,
        )
    except Exception as exc:
        logger.warning("search_eval.llm_failed error=%s attempt=%s", exc, attempt)
        evaluated = None

    if heuristic.retry_sub_query is not None:
        if evaluated and evaluated.retry_query:
            return SearchEvaluation(
                sufficient=False,
                should_retry=True,
                retry_query=evaluated.retry_query,
                reason=evaluated.reason or heuristic.reason,
                retry_sub_query=heuristic.retry_sub_query,
                coverage=heuristic.coverage,
            )
        return heuristic

    if heuristic.sufficient:
        if evaluated and evaluated.sufficient:
            return SearchEvaluation(
                sufficient=True,
                should_retry=False,
                retry_query="",
                reason=evaluated.reason or heuristic.reason,
                coverage=evaluated.coverage or heuristic.coverage,
            )
        return heuristic

    if not evaluated:
        return heuristic

    retry_sub_query = evaluated.retry_sub_query
    if retry_sub_query is None and plan.sub_queries:
        for sub_query in plan.sub_queries:
            if not heuristic.coverage.get(sub_query.query, False):
                retry_sub_query = sub_query
                break

    if evaluated.sufficient:
        return SearchEvaluation(
            sufficient=True,
            should_retry=False,
            retry_query="",
            reason=evaluated.reason or heuristic.reason,
            coverage=evaluated.coverage or heuristic.coverage,
        )

    if evaluated.retry_query:
        return SearchEvaluation(
            sufficient=False,
            should_retry=True,
            retry_query=evaluated.retry_query,
            reason=evaluated.reason or heuristic.reason,
            retry_sub_query=retry_sub_query,
            coverage=evaluated.coverage or heuristic.coverage,
        )

    return heuristic


def evaluate_search_step(
    original_request: str,
    query: str,
    results: list[NormalizedResult | dict],
    pages: list[NormalizedResult | dict],
) -> SearchEvaluation:
    results = _normalize_results(results)
    pages = _normalize_results(pages)
    heuristic = _heuristic_search_evaluation(original_request, query, results, pages)
    try:
        evaluated = _evaluate_with_model(original_request, query, results, pages)
    except Exception as exc:
        logger.warning("search_eval.llm_failed error=%s", exc)
        evaluated = None

    if heuristic.sufficient:
        if evaluated and evaluated.sufficient:
            return SearchEvaluation(
                sufficient=True,
                should_retry=False,
                retry_query="",
                reason=evaluated.reason or heuristic.reason,
                coverage=heuristic.coverage,
            )
        return heuristic

    if not evaluated:
        return heuristic

    retry_query = (evaluated.retry_query or "").strip()
    if retry_query:
        return SearchEvaluation(
            sufficient=False,
            should_retry=True,
            retry_query=retry_query,
            reason=evaluated.reason or heuristic.reason,
            coverage=heuristic.coverage,
        )

    return heuristic


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def build_search_task(
    chat_id: int,
    user_text: str,
    *,
    turn_context_msgs: list[dict] | None = None,
) -> SearchTask:
    context = await _select_search_context(
        chat_id,
        user_text,
        turn_context_msgs=turn_context_msgs,
    )
    return _enrich_weather_task(
        _build_single_search_task_from_context(user_text, context)
    )


async def plan_search_queries(
    user_text: str,
    dialogue_excerpt: list[dict],
    mode_hint: str | None = None,
    *,
    fallback_task: SearchTask | None = None,
) -> SearchPlan:
    base_task = fallback_task or _build_single_search_task_from_context(
        user_text,
        trim_terminal_user_duplicate(dialogue_excerpt, user_text),
    )
    fallback_plan = _heuristic_plan_from_task(base_task)

    try:
        planned = _plan_with_model(
            user_text,
            dialogue_excerpt,
            mode_hint=mode_hint or base_task.mode,
        )
    except Exception as exc:
        logger.warning("search_plan.llm_failed error=%s", exc)
        planned = None

    if not planned or not planned.sub_queries:
        return fallback_plan

    return SearchPlan(
        sub_queries=planned.sub_queries,
        original_request=user_text,
        needs_extract=bool(planned.needs_extract or fallback_plan.needs_extract),
        recency_days=(
            planned.recency_days
            if planned.recency_days is not None
            else fallback_plan.recency_days
        ),
    )


async def build_search_tasks(
    chat_id: int,
    user_text: str,
    *,
    turn_context_msgs: list[dict] | None = None,
) -> list[SearchTask]:
    context = await _select_search_context(
        chat_id,
        user_text,
        turn_context_msgs=turn_context_msgs,
    )
    base_task = _build_single_search_task_from_context(user_text, context)
    plan = await plan_search_queries(
        user_text,
        context,
        mode_hint=base_task.mode,
        fallback_task=base_task,
    )
    return _tasks_from_plan(base_task, plan)
