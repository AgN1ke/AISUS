from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field, replace

from agent.llm import chat_once, make_messages, tool_spec
from agent.search_task import (
    EvidencePack,
    NormalizedResult,
    SearchPlan,
    SearchTask,
    SubQuery,
    build_search_tasks,
    evaluate_evidence,
    evaluate_search_step,
    has_search_coverage,
    is_explicit_search_request,
    normalize_search_query,
    suggest_retry_query,
    trim_terminal_user_duplicate,
)
from agent.tools.web_search import extract_search_pages, search_web
from core.env import capability_model, env_bool, env_int
from core.prompts import (
    AGENT_TOOL_SYSTEM_PROMPT,
    capability_system_prompt,
    search_synthesis_system_prompt,
)
from memory import memory_manager

logger = logging.getLogger(__name__)

_LEGACY_UNUSED_SEARCH_INTENT_PATTERNS = [
    r"\bпошукай\b",
    r"\bпогугли\b",
    r"\bзагугли\b",
    r"\bзнайди\s+в\s+інтернеті\b",
    r"\bперевір\s+в\s+інтернеті\b",
    r"\bщо\s+нового\b",
    r"\bновини\b",
    r"\bактуальні\s+новини\b",
]


def _thinking_enabled() -> bool:
    return env_bool("THINKING_ENABLED", default=True)


def _search_enabled() -> bool:
    return env_bool("SEARCH_ENABLED", default=True)


def _max_steps() -> int:
    return env_int("REASONING_MAX_STEPS", default=3)


def _search_fetch_pages() -> int:
    return env_int("SEARCH_FETCH_PAGES", default=2)


def _search_page_chars() -> int:
    return env_int("SEARCH_PAGE_MAX_CHARS", default=4000)


def _search_total_evidence_chars() -> int:
    return env_int("SEARCH_TOTAL_EVIDENCE_CHARS", default=12000)


def _search_snippet_chars() -> int:
    return env_int("SEARCH_SNIPPET_MAX_CHARS", default=500)


def _search_max_results() -> int:
    return env_int("SEARCH_MAX_RESULTS", default=5)


def _search_max_iterations() -> int:
    return max(1, min(env_int("SEARCH_MAX_ITERATIONS", default=3), 3))


def _is_explicit_search_intent(user_text: str) -> bool:
    return is_explicit_search_request(user_text)


@dataclass
class SearchOutcome:
    """Result of running web search before composition by chat_final.

    The evidence_block is plain text formatted for inclusion as a system
    [SEARCH-RESULT] message in chat_final's context. Status reflects what
    actually happened so chat_final can phrase the answer (or refusal)
    naturally.
    """
    status: str  # "ok" | "best_effort" | "no_results" | "insufficient_evidence"
    evidence_block: str
    queries: list[str] = field(default_factory=list)
    citation_map: dict[int, str] = field(default_factory=dict)
    intent_hypothesis: str = ""


def _today_iso() -> str:
    return _dt.datetime.utcnow().date().isoformat()


def _now_system_msg() -> dict:
    return {
        "role": "system",
        "content": f"[NOW]\ntoday_date_utc: {_today_iso()}",
    }


def _should_use_agent(user_text: str) -> bool:
    strict = env_bool("THINKING_STRICT", default=True)
    text = (user_text or "").strip().lower()
    if text.startswith("/think") or _is_explicit_search_intent(text):
        return True
    if strict:
        return False
    return _thinking_enabled()


def _needs_reasoning(user_text: str) -> bool:
    """Reasoning trigger: only explicit '/think' prefix.

    Per audit (Session 101 round 2, B-004/B-005 → DROP):
    - 🧠 emoji removed (could appear in normal text by accident)
    - 'роздумай' / 'step-by-step' / 'use reasoning' phrases removed (too fuzzy,
      hard to verify, unintended activations)
    """
    text = (user_text or "").strip().lower()
    return text.startswith("/think")


def _normalize_query(user_text: str) -> str:
    return normalize_search_query(user_text)


def _format_sources(sources: list[NormalizedResult]) -> str:
    del sources
    return ""


def _strip_sources_block(answer: str) -> str:
    text = (answer or "").strip()
    if not text:
        return ""
    marker = "\n\nДжерела:\n"
    if marker in text:
        text = text.split(marker, 1)[0].strip()
    return text


def _build_search_memory_event(
    original_request: str,
    planned_queries: list[str],
    results: list[NormalizedResult],
    answer: str,
    *,
    status: str,
) -> str:
    lines = ["[SEARCH]"]
    request = (original_request or "").strip()
    if request:
        lines.append(f"request: {request[:1200]}")
    if planned_queries:
        lines.append("queries:")
        for query in planned_queries[:3]:
            cleaned = (query or "").strip()
            if cleaned:
                lines.append(f"- {cleaned[:240]}")
    lines.append(f"status: {status}")
    summary = _strip_sources_block(answer)
    if summary:
        lines.append(f"answer_summary: {summary[:1500]}")
    if results:
        lines.append("top_results:")
        for result in results[:5]:
            title = (result.title or result.url or "result").strip()
            domain = (result.domain or "").strip()
            snippet = (result.snippet or "").strip()
            row = title[:200]
            if domain:
                row = f"{row} — {domain}"
            lines.append(f"- {row}")
            if snippet:
                lines.append(f"  {snippet[:300]}")
    return "\n".join(lines).strip()


async def _append_search_memory_event(
    chat_id: int,
    original_request: str,
    planned_queries: list[str],
    results: list[NormalizedResult],
    answer: str,
    *,
    status: str,
) -> None:
    content = _build_search_memory_event(
        original_request,
        planned_queries,
        results,
        answer,
        status=status,
    )
    if not content:
        return
    try:
        await memory_manager.append_message(chat_id, "system", content)
        await memory_manager.ensure_budget(chat_id)
    except Exception as exc:
        logger.warning(
            "search.memory_append_failed chat_id=%s status=%s error=%s",
            chat_id,
            status,
            exc,
        )


def _format_search_hits(results: list[NormalizedResult]) -> str:
    lines = []
    for idx, result in enumerate(results, start=1):
        title = result.title or f"Результат {idx}"
        url = result.url or ""
        snippet = result.snippet.strip()
        lines.append(f"[{idx}] {title}")
        if url:
            lines.append(f"URL: {url}")
        if snippet:
            lines.append(f"Snippet: {snippet}")
        lines.append(f"Provider: {result.source_provider}")
        lines.append(f"Relevance: {result.relevance_score:.2f}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_page_evidence(pages: list[NormalizedResult]) -> str:
    blocks = []
    for idx, page in enumerate(pages, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[PAGE {idx}] {page.title or page.url or 'Сторінка'}",
                    f"URL: {page.url or ''}",
                    page.full_content or "",
                ]
            ).strip()
        )
    return "\n\n".join(blocks).strip()


def _search_evidence_is_actionable(
    results: list[NormalizedResult], pages: list[NormalizedResult]
) -> bool:
    if pages:
        return True
    if len(results) < 3:
        return False
    domains = {result.domain for result in results if result.domain}
    return len(domains) >= 2


def _item_value(item: dict | object, field: str) -> str:
    if isinstance(item, dict):
        return str(item.get(field) or "").strip()
    return str(getattr(item, field, "") or "").strip()


def _merge_unique_items(
    target: list[dict] | list[NormalizedResult],
    incoming: list[dict] | list[NormalizedResult],
    *key_fields: str,
) -> None:
    seen = {tuple(_item_value(item, field) for field in key_fields) for item in target}
    for item in incoming:
        key = tuple(_item_value(item, field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        target.append(item)


def _system_prompt_for_capability(capability: str) -> str:
    return capability_system_prompt(capability)


def _merge_turn_context(
    context_msgs: list[dict],
    turn_context_msgs: list[dict] | None = None,
) -> list[dict]:
    if not turn_context_msgs:
        return context_msgs
    # Current-turn geometry/media/search evidence must be the freshest context
    # the model sees. Put it after recalled memory, immediately before the
    # terminal user message added by make_messages().
    return list(context_msgs) + list(turn_context_msgs)


@dataclass(frozen=True)
class SynthesisInput:
    user_intent: str
    evidence: EvidencePack
    style_policy: str
    dialogue_context: list[dict]


_INLINE_CITATION_RE = re.compile(r"(?<!\[)\[(\d{1,2})\](?!\()")
_LINKED_CITATION_RE = re.compile(r"\[\[(\d{1,2})\]\]\((https?://[^\s)]+)\)")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(https?://[^\s)]+\)")


def _truncate_evidence_text(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    if not value or limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return value[: max(limit - 3, 0)].rstrip() + "..."


def _search_item_key(item: NormalizedResult) -> tuple[str, str, str]:
    return (
        (item.url or "").strip().lower(),
        (item.domain or "").strip().lower(),
        (item.title or "").strip().lower(),
    )


def _preferred_search_item(
    current: NormalizedResult | None,
    candidate: NormalizedResult,
) -> NormalizedResult:
    if current is None:
        return candidate
    current_score = (
        bool(current.full_content),
        len(current.full_content or ""),
        current.relevance_score,
        len(current.snippet or ""),
    )
    candidate_score = (
        bool(candidate.full_content),
        len(candidate.full_content or ""),
        candidate.relevance_score,
        len(candidate.snippet or ""),
    )
    return candidate if candidate_score > current_score else current


def _merge_results_and_pages(
    results: list[NormalizedResult],
    pages: list[NormalizedResult],
) -> list[NormalizedResult]:
    merged: dict[tuple[str, str, str], NormalizedResult] = {}
    for item in [*results, *pages]:
        key = _search_item_key(item)
        merged[key] = _preferred_search_item(merged.get(key), item)
    return _rank_search_items(list(merged.values()))


def reorder_for_llm(items: list[NormalizedResult]) -> list[NormalizedResult]:
    ranked = _rank_search_items(items)
    if len(ranked) <= 2:
        return ranked
    front: list[NormalizedResult] = []
    back: list[NormalizedResult] = []
    for index, item in enumerate(ranked):
        if index % 2 == 0:
            front.append(item)
        else:
            back.append(item)
    return front + list(reversed(back))


def _build_synthesis_dialogue_context(
    context_msgs: list[dict],
    *,
    limit: int = 4,
) -> list[dict]:
    dialogue: list[dict] = []
    for msg in context_msgs:
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        if not content or content.startswith("["):
            continue
        dialogue.append({"role": role, "content": content[:600]})
    return dialogue[-limit:]


def _format_dialogue_context(dialogue_context: list[dict]) -> str:
    lines: list[str] = []
    for msg in dialogue_context:
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        prefix = "user" if role == "user" else "assistant"
        lines.append(f"{prefix}: {content}")
    return "\n".join(lines).strip()


def _format_synthesis_evidence(
    evidence: EvidencePack,
) -> tuple[str, dict[int, str]]:
    merged_items = reorder_for_llm(
        _merge_results_and_pages(evidence.results, evidence.pages)
    )
    numbered_items = merged_items[:8]
    extracted_items = [item for item in numbered_items if item.full_content]
    total_excerpt_budget = _search_total_evidence_chars()
    per_page_budget = (
        min(
            _search_page_chars(),
            max(1200, total_excerpt_budget // max(len(extracted_items), 1)),
        )
        if extracted_items
        else 0
    )
    remaining_excerpt_budget = total_excerpt_budget
    blocks: list[str] = []
    citation_map: dict[int, str] = {}

    for index, item in enumerate(numbered_items, start=1):
        citation_map[index] = item.url
        lines = [f"[{index}] {item.title or item.url or f'Result {index}'}"]
        if item.url:
            lines.append(f"URL: {item.url}")
        if item.published_date:
            lines.append(f"Published: {item.published_date}")
        snippet = _truncate_evidence_text(item.snippet, _search_snippet_chars())
        if snippet:
            lines.append(f"Snippet: {snippet}")
        if item.full_content and remaining_excerpt_budget > 0:
            excerpt_limit = min(per_page_budget, remaining_excerpt_budget)
            excerpt = _truncate_evidence_text(item.full_content, excerpt_limit)
            if excerpt:
                lines.append(f"Excerpt: {excerpt}")
                remaining_excerpt_budget -= len(excerpt)
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks).strip(), citation_map


def _build_synthesis_input(
    user_text: str,
    evidence: EvidencePack,
    context_msgs: list[dict],
) -> SynthesisInput:
    return SynthesisInput(
        user_intent=(user_text or "").strip(),
        evidence=evidence,
        style_policy=(
            "Keep the same bot persona and Telegram tone, but do not mention internal search steps."
        ),
        dialogue_context=_build_synthesis_dialogue_context(context_msgs),
    )


def _build_synthesis_user_message(
    synthesis_input: SynthesisInput,
) -> tuple[str, dict[int, str]]:
    evidence_text, citation_map = _format_synthesis_evidence(synthesis_input.evidence)
    parts = [f"User intent:\n{synthesis_input.user_intent}"]
    dialogue_text = _format_dialogue_context(synthesis_input.dialogue_context)
    if dialogue_text:
        parts.append(f"Recent dialogue context for tone only:\n{dialogue_text}")
    if synthesis_input.style_policy:
        parts.append(f"Style policy:\n{synthesis_input.style_policy}")
    parts.append(f"Evidence:\n{evidence_text}")
    return "\n\n".join(part for part in parts if part.strip()), citation_map


def _domain_label_from_url(url: str) -> str:
    """Extract a clean domain label like 'nasa.gov' for citation rendering."""
    try:
        netloc = urllib.parse.urlparse((url or "").strip()).netloc
    except Exception:
        return ""
    netloc = (netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or ""


def _apply_inline_citation_links(
    answer: str,
    citation_map: dict[int, str],
) -> str:
    """Replace `[N]` and `[[N]](url)` with `[domain.com](url)`.

    B-070: switched from `[[N]](url)` numeric format (where the number was
    often wrong/duplicated) to domain-based labels — readers see the source
    immediately.
    """
    if not citation_map:
        return answer

    # First pass: convert already-linked [[N]](url) directly to [domain](url)
    def replace_linked(match: re.Match[str]) -> str:
        url = (match.group(2) or "").strip()
        domain = _domain_label_from_url(url)
        if not domain:
            return match.group(0)
        return f"[{domain}]({url})"

    answer = _LINKED_CITATION_RE.sub(replace_linked, answer)

    # Second pass: bare [N] → [domain](url) using citation_map
    def replace_bare(match: re.Match[str]) -> str:
        index = int(match.group(1))
        url = (citation_map.get(index) or "").strip()
        if not url:
            return match.group(0)
        domain = _domain_label_from_url(url)
        if not domain:
            return match.group(0)
        return f"[{domain}]({url})"

    return _INLINE_CITATION_RE.sub(replace_bare, answer)


def _ensure_answer_has_citations(
    answer: str,
    citation_map: dict[int, str],
) -> str:
    """Append `[domain](url)` references to the end if model produced no citations."""
    if not citation_map:
        return answer
    if (
        _MARKDOWN_LINK_RE.search(answer)
        or _LINKED_CITATION_RE.search(answer)
        or _INLINE_CITATION_RE.search(answer)
    ):
        return answer
    parts: list[str] = []
    for _index, url in list(citation_map.items())[:2]:
        if not url:
            continue
        domain = _domain_label_from_url(url)
        if domain:
            parts.append(f"[{domain}]({url})")
    if not parts:
        return answer
    return f"{answer.rstrip()} {' '.join(parts)}".strip()


def _citation_map_from_results(results: list[NormalizedResult]) -> dict[int, str]:
    return {
        index: item.url
        for index, item in enumerate(results[:8], start=1)
        if (item.url or "").strip()
    }


async def _collect_search_evidence(
    task: SearchTask,
    query: str,
    *,
    coverage_key: str,
) -> EvidencePack:
    results = await search_web(
        query,
        _search_max_results(),
        task.recency_days,
        mode=task.mode,
        profile=getattr(task, "profile", task.mode),
        preferred_domains=task.preferred_domains,
        preferred_domains_deny=getattr(task, "preferred_domains_deny", ()),
        country=getattr(task, "country", None),
        languages=getattr(task, "languages", ()),
        provider_hint=getattr(task, "provider_hint", None),
    )
    profile = getattr(task, "profile", task.mode)
    should_extract = bool(
        getattr(task, "need_extract", False)
        or getattr(task, "need_primary_source", False)
        or profile in {"docs", "research_paper", "site_search"}
    )
    pages: list[NormalizedResult] = []
    if should_extract:
        pages = await extract_search_pages(
            query,
            results,
            max_pages=_search_fetch_pages(),
            max_chars=_search_page_chars(),
            profile=profile,
            need_primary_source=getattr(task, "need_primary_source", False),
        )
    task_evaluation = evaluate_search_step(
        task.original_request,
        query,
        results,
        pages,
    )
    task_coverage = bool(
        has_search_coverage(results, pages) and task_evaluation.sufficient
    )
    retry_query = (task_evaluation.retry_query or "").strip() or suggest_retry_query(
        task.original_request,
        query,
        alternatives=getattr(task, "alternative_queries", ()),
    )
    evidence = EvidencePack(
        results=list(results),
        sub_query_coverage={coverage_key: task_coverage},
        total_providers_used=len(
            {
                item.source_provider
                for item in [*results, *pages]
                if item.source_provider
            }
        ),
        total_results_before_filter=len(results),
        extraction_attempted=should_extract,
        pages=list(pages),
        retry_queries={coverage_key: retry_query} if retry_query else {},
    )
    return evidence


def _rank_search_items(items: list[NormalizedResult]) -> list[NormalizedResult]:
    best_by_key: dict[tuple[str, str], NormalizedResult] = {}
    for item in items:
        key = (
            (item.domain or "").lower(),
            (item.title or "")[:50].lower(),
        )
        current = best_by_key.get(key)
        if current is None:
            best_by_key[key] = item
            continue
        current_score = (
            current.relevance_score,
            bool(current.full_content),
            len(current.full_content or ""),
        )
        candidate_score = (
            item.relevance_score,
            bool(item.full_content),
            len(item.full_content or ""),
        )
        if candidate_score > current_score:
            best_by_key[key] = item
    return sorted(
        best_by_key.values(),
        key=lambda item: (
            item.relevance_score,
            bool(item.full_content),
            len(item.full_content or ""),
        ),
        reverse=True,
    )


def _search_plan_from_tasks(user_text: str, tasks: list[SearchTask]) -> SearchPlan:
    sub_queries = []
    for task in tasks:
        alternative = next(
            (
                alternative
                for alternative in getattr(task, "alternative_queries", ())
                if alternative.strip()
                and alternative.strip().lower() != (task.query or "").strip().lower()
            ),
            None,
        )
        sub_queries.append(
            SubQuery(
                query=task.query,
                profile=getattr(task, "profile", task.mode),
                alternative=alternative,
                provider_hint=getattr(task, "provider_hint", None),
            )
        )
    recency_days = next(
        (task.recency_days for task in tasks if task.recency_days), None
    )
    return SearchPlan(
        sub_queries=tuple(sub_queries),
        original_request=user_text,
        needs_extract=any(getattr(task, "need_extract", False) for task in tasks),
        recency_days=recency_days,
    )


async def _search_single_task(
    chat_id: int,
    task_index: int,
    task_count: int,
    coverage_key: str,
    task: SearchTask,
) -> tuple[str, EvidencePack]:
    current_query = (task.query or "").strip()
    logger.info(
        "search.task_start chat_id=%s task=%s/%s query=%s source=%s profile=%s mode=%s recency=%s alt=%s",
        chat_id,
        task_index,
        task_count,
        current_query[:200],
        task.source,
        getattr(task, "profile", task.mode),
        task.mode,
        task.recency_days,
        len(getattr(task, "alternative_queries", ()) or ()),
    )
    evidence = await _collect_search_evidence(
        task,
        current_query,
        coverage_key=coverage_key,
    )
    logger.info(
        "search.task_finish chat_id=%s task=%s/%s query=%s results=%s pages=%s coverage=%s",
        chat_id,
        task_index,
        task_count,
        current_query[:200],
        len(evidence.results),
        len(evidence.pages),
        evidence.sub_query_coverage.get(coverage_key, False),
    )
    return current_query, evidence


async def _collect_all_evidence(
    chat_id: int,
    task_specs: list[tuple[str, SearchTask]],
) -> tuple[EvidencePack, list[str]]:
    if not task_specs:
        return (
            EvidencePack(
                results=[],
                sub_query_coverage={},
                total_providers_used=0,
                total_results_before_filter=0,
                extraction_attempted=False,
                pages=[],
                retry_queries={},
            ),
            [],
        )

    coroutines = [
        _search_single_task(chat_id, index, len(task_specs), coverage_key, task)
        for index, (coverage_key, task) in enumerate(task_specs, start=1)
    ]
    raw_batches = await asyncio.gather(*coroutines, return_exceptions=True)

    all_results: list[NormalizedResult] = []
    all_pages: list[NormalizedResult] = []
    coverage: dict[str, bool] = {coverage_key: False for coverage_key, _ in task_specs}
    retry_queries: dict[str, str] = {}
    providers: set[str] = set()
    total_results_before_filter = 0
    extraction_attempted = False
    executed_queries: list[str] = []

    for (coverage_key, task), batch in zip(task_specs, raw_batches):
        if isinstance(batch, Exception):
            logger.warning(
                "search.task_failed chat_id=%s query=%s error=%s",
                chat_id,
                (task.query or "")[:200],
                batch,
            )
            fallback_retry = suggest_retry_query(
                task.original_request,
                task.query,
                alternatives=getattr(task, "alternative_queries", ()),
            )
            if fallback_retry:
                retry_queries[coverage_key] = fallback_retry
            continue

        executed_query, evidence = batch
        executed_queries.append(executed_query)
        all_results.extend(evidence.results)
        all_pages.extend(evidence.pages)
        total_results_before_filter += evidence.total_results_before_filter
        extraction_attempted = extraction_attempted or evidence.extraction_attempted
        for key, is_covered in evidence.sub_query_coverage.items():
            coverage[key] = coverage.get(key, False) or bool(is_covered)
        for key, retry_query in evidence.retry_queries.items():
            if retry_query and not retry_queries.get(key):
                retry_queries[key] = retry_query
        providers.update(
            item.source_provider
            for item in [*evidence.results, *evidence.pages]
            if item.source_provider
        )

    return (
        EvidencePack(
            results=_rank_search_items(all_results),
            sub_query_coverage=coverage,
            total_providers_used=len(providers),
            total_results_before_filter=total_results_before_filter,
            extraction_attempted=extraction_attempted,
            pages=_rank_search_items(all_pages),
            retry_queries=retry_queries,
        ),
        executed_queries,
    )


async def _run_direct_search(
    chat_id: int,
    user_text: str,
    use_reasoning: bool,
    *,
    turn_context_msgs: list[dict] | None = None,
) -> SearchOutcome:
    tasks = await build_search_tasks(
        chat_id,
        user_text,
        turn_context_msgs=turn_context_msgs,
    )
    tasks = [task for task in tasks if (task.query or "").strip()]
    model = capability_model("search_synthesis")
    planned_queries = [task.query for task in tasks]
    logger.info(
        "search.start chat_id=%s tasks=%s queries=%s",
        chat_id,
        len(tasks),
        [query[:120] for query in planned_queries],
    )

    if not tasks:
        logger.warning("search.empty_query chat_id=%s", chat_id)
        return SearchOutcome(
            status="no_results",
            evidence_block=(
                "status: no_results\n"
                "details: пошуковий планувальник не повернув жодного валідного "
                "запиту для цього повідомлення."
            ),
            queries=[],
        )

    context = await memory_manager.select_context(
        chat_id=chat_id, user_query=user_text, system_prompt=None
    )
    context = _merge_turn_context(context, turn_context_msgs)
    context = trim_terminal_user_duplicate(context, user_text)
    plan = _search_plan_from_tasks(user_text, tasks)
    task_by_query = {task.query: task for task in tasks}
    attempted_queries = {
        task.query: {(task.query or "").strip().lower()}
        for task in tasks
        if (task.query or "").strip()
    }
    aggregated_results: list[NormalizedResult] = []
    aggregated_pages: list[NormalizedResult] = []
    aggregated_coverage = {sub_query.query: False for sub_query in plan.sub_queries}
    aggregated_retry_queries: dict[str, str] = {}
    provider_names: set[str] = set()
    total_results_before_filter = 0
    extraction_attempted = False
    executed_queries: list[str] = []
    total_attempts = 0
    pending_specs: list[tuple[str, SearchTask]] = [(task.query, task) for task in tasks]
    evaluation = None
    extract_attempted_keys: set[str] = set()

    for attempt in range(1, _search_max_iterations() + 1):
        for coverage_key, pending_task in pending_specs:
            if getattr(pending_task, "need_extract", False):
                extract_attempted_keys.add(coverage_key)
        total_attempts += len(pending_specs)
        logger.info(
            "search.parallel_attempt_start chat_id=%s attempt=%s/%s pending=%s",
            chat_id,
            attempt,
            _search_max_iterations(),
            len(pending_specs),
        )
        batch_evidence, batch_queries = await _collect_all_evidence(
            chat_id, pending_specs
        )
        executed_queries.extend(batch_queries)
        aggregated_results.extend(batch_evidence.results)
        aggregated_pages.extend(batch_evidence.pages)
        aggregated_results = _rank_search_items(aggregated_results)
        aggregated_pages = _rank_search_items(aggregated_pages)
        total_results_before_filter += batch_evidence.total_results_before_filter
        extraction_attempted = (
            extraction_attempted or batch_evidence.extraction_attempted
        )
        for key, is_covered in batch_evidence.sub_query_coverage.items():
            aggregated_coverage[key] = aggregated_coverage.get(key, False) or bool(
                is_covered
            )
        for key, retry_query in batch_evidence.retry_queries.items():
            if retry_query and not aggregated_retry_queries.get(key):
                aggregated_retry_queries[key] = retry_query
        provider_names.update(
            item.source_provider
            for item in [*batch_evidence.results, *batch_evidence.pages]
            if item.source_provider
        )

        aggregated_evidence = EvidencePack(
            results=aggregated_results,
            sub_query_coverage=aggregated_coverage,
            total_providers_used=len(provider_names),
            total_results_before_filter=total_results_before_filter,
            extraction_attempted=extraction_attempted,
            pages=aggregated_pages,
            retry_queries=aggregated_retry_queries,
        )
        logger.info(
            "search.parallel_evidence chat_id=%s attempt=%s results=%s pages=%s coverage=%s",
            chat_id,
            attempt,
            len(aggregated_results),
            len(aggregated_pages),
            aggregated_coverage,
        )
        evaluation = evaluate_evidence(
            plan,
            aggregated_evidence,
            attempt=attempt,
        )
        logger.info(
            "search.parallel_evaluate chat_id=%s attempt=%s sufficient=%s retry=%s reason=%s coverage=%s",
            chat_id,
            attempt,
            evaluation.sufficient,
            bool(evaluation.retry_query),
            evaluation.reason,
            evaluation.coverage,
        )
        if evaluation.sufficient:
            break

        if attempt >= _search_max_iterations():
            logger.info(
                "search.retry_stop chat_id=%s attempt=%s reason=max_iterations",
                chat_id,
                attempt,
            )
            break
        if not evaluation.should_retry or evaluation.retry_sub_query is None:
            logger.info(
                "search.retry_stop chat_id=%s attempt=%s reason=no_targeted_retry",
                chat_id,
                attempt,
            )
            break

        coverage_key = evaluation.retry_sub_query.query
        base_task = task_by_query.get(coverage_key)
        if (
            base_task
            and coverage_key not in extract_attempted_keys
            and not getattr(base_task, "need_extract", False)
        ):
            extract_attempted_keys.add(coverage_key)
            pending_specs = [
                (
                    coverage_key,
                    replace(
                        base_task,
                        need_extract=True,
                        source=f"{base_task.source}:extract",
                    ),
                )
            ]
            logger.info(
                "search.extract_scheduled chat_id=%s attempt=%s target=%s query=%s",
                chat_id,
                attempt,
                coverage_key[:200],
                (base_task.query or "")[:200],
            )
            continue

        retry_query = (evaluation.retry_query or "").strip()
        if not base_task or not retry_query:
            logger.info(
                "search.retry_stop chat_id=%s attempt=%s reason=missing_retry_query target=%s",
                chat_id,
                attempt,
                coverage_key[:200],
            )
            break

        attempted_for_key = attempted_queries.setdefault(coverage_key, set())
        if retry_query.lower() in attempted_for_key:
            logger.info(
                "search.retry_stop chat_id=%s attempt=%s reason=duplicate_query target=%s",
                chat_id,
                attempt,
                coverage_key[:200],
            )
            break

        attempted_for_key.add(retry_query.lower())
        pending_specs = [
            (
                coverage_key,
                replace(
                    base_task,
                    query=retry_query,
                    source=f"{base_task.source}:retry",
                ),
            )
        ]
        logger.info(
            "search.retry_scheduled chat_id=%s attempt=%s target=%s next_query=%s",
            chat_id,
            attempt,
            coverage_key[:200],
            retry_query[:200],
        )

    if not aggregated_results:
        failure_text = (
            "status: no_results\n"
            "details: пошук відпрацював, але провайдери не повернули нічого "
            "придатного для відповіді на цей запит."
        )
        await _append_search_memory_event(
            chat_id,
            user_text,
            planned_queries,
            [],
            failure_text,
            status="no_results",
        )
        logger.warning(
            "search.no_results chat_id=%s queries=%s attempts=%s",
            chat_id,
            [query[:120] for query in executed_queries],
            total_attempts,
        )
        return SearchOutcome(
            status="no_results",
            evidence_block=failure_text,
            queries=planned_queries,
        )

    final_sufficient = bool(evaluation and evaluation.sufficient)
    if not final_sufficient and _search_evidence_is_actionable(
        aggregated_results,
        aggregated_pages,
    ):
        final_sufficient = True

    if not final_sufficient:
        partial_block = _build_evidence_block(
            user_text=user_text,
            planned_queries=planned_queries,
            aggregated_results=aggregated_results,
            aggregated_pages=aggregated_pages,
            status_label="insufficient_evidence",
            note=(
                "Зібрані результати неповні. Не вигадуй того, чого тут немає; "
                "якщо для відповіді на запит даних мало — прямо скажи це юзеру."
            ),
        )
        await _append_search_memory_event(
            chat_id,
            user_text,
            planned_queries,
            aggregated_results,
            partial_block,
            status="insufficient_evidence",
        )
        logger.warning(
            "search.insufficient_evidence chat_id=%s queries=%s attempts=%s results=%s pages=%s coverage=%s",
            chat_id,
            [query[:120] for query in executed_queries],
            total_attempts,
            len(aggregated_results),
            len(aggregated_pages),
            aggregated_coverage,
        )
        return SearchOutcome(
            status="insufficient_evidence",
            evidence_block=partial_block,
            queries=planned_queries,
            citation_map=_citation_map_from_results(aggregated_results),
        )

    status_label = "ok"
    evidence_block = _build_evidence_block(
        user_text=user_text,
        planned_queries=planned_queries,
        aggregated_results=aggregated_results,
        aggregated_pages=aggregated_pages,
        status_label=status_label,
    )
    await _append_search_memory_event(
        chat_id,
        user_text,
        planned_queries,
        aggregated_results,
        evidence_block,
        status=status_label,
    )
    logger.info(
        "search.finish chat_id=%s status=%s sources=%s pages=%s attempts=%s tasks=%s coverage=%s",
        chat_id,
        status_label,
        len(aggregated_results),
        len(aggregated_pages),
        total_attempts,
        len(tasks),
        aggregated_coverage,
    )
    return SearchOutcome(
        status=status_label,
        evidence_block=evidence_block,
        queries=planned_queries,
        citation_map=_citation_map_from_results(aggregated_results),
    )


def _build_evidence_block(
    *,
    user_text: str,
    planned_queries: list[str],
    aggregated_results: list[NormalizedResult],
    aggregated_pages: list[NormalizedResult],
    status_label: str,
    note: str | None = None,
) -> str:
    """Format the [SEARCH-RESULT] payload that chat_final will read."""
    parts: list[str] = []
    parts.append(f"status: {status_label}")
    parts.append(f"original_query:\n  {user_text.strip()}")
    if planned_queries:
        parts.append(
            "sub_queries:\n"
            + "\n".join(f"  - {query}" for query in planned_queries)
        )
    if note:
        parts.append(f"note: {note}")
    if aggregated_results:
        parts.append("results:\n" + _format_search_hits(aggregated_results))
    page_block = _format_page_evidence(aggregated_pages)
    if page_block:
        parts.append("pages:\n" + page_block)
    parts.append(
        "instructions:\n"
        "  - Це результати веб-пошуку, виконані за рішенням планувальника.\n"
        "  - Відповідай юзеру СВОЇМИ словами в стилі бесіди, спираючись на ці результати.\n"
        "  - Можеш цитувати конкретні факти інлайн через [N] — посилання беруться з results.\n"
        "  - Не додавай окремий блок 'Джерела' з URL, не дампи URL текстом.\n"
        "  - Якщо в results нема нічого по темі — чесно скажи юзеру, що в інтернеті\n"
        "    конкретно по цьому запиту нічого надійного не знайшлось, і запропонуй\n"
        "    переформулювати або уточнити (без копіпасти службового тексту)."
    )
    return "\n\n".join(parts)


async def run_search(
    chat_id: int,
    user_text: str,
    use_reasoning: bool = False,
    *,
    turn_context_msgs: list[dict] | None = None,
) -> str:
    """Run web search, then ask chat_final to compose the user-facing reply.

    The search planner picks queries and runs retrieval. The full evidence is
    handed to the main chat_final model as a [SEARCH-RESULT] system message
    in its context, alongside dialogue history. chat_final composes the reply
    naturally — adapted to Telegram, in its own voice — instead of relying on
    a separate synthesis model.
    """
    outcome = await _run_direct_search(
        chat_id,
        user_text,
        use_reasoning,
        turn_context_msgs=turn_context_msgs,
    )

    search_msg = {
        "role": "system",
        "content": f"[SEARCH-RESULT]\n{outcome.evidence_block}",
    }
    augmented_ctx = list(turn_context_msgs or []) + [search_msg]
    answer = await run_capability(
        chat_id,
        user_text,
        capability="chat_final",
        use_reasoning=use_reasoning,
        turn_context_msgs=augmented_ctx,
    )
    answer = (answer or "").strip()
    answer = _apply_inline_citation_links(answer, outcome.citation_map)
    answer = _ensure_answer_has_citations(answer, outcome.citation_map)
    return answer


async def run_capability(
    chat_id: int,
    user_text: str,
    capability: str = "chat_final",
    use_reasoning: bool = False,
    *,
    turn_context_msgs: list[dict] | None = None,
) -> str:
    logger.info(
        "capability.start chat_id=%s capability=%s text_len=%s reasoning=%s",
        chat_id,
        capability,
        len(user_text or ""),
        use_reasoning,
    )
    context = await memory_manager.select_context(
        chat_id=chat_id, user_query=user_text, system_prompt=None
    )
    context = _merge_turn_context(context, turn_context_msgs)
    context = trim_terminal_user_duplicate(context, user_text)
    # Inject current date so the model can reason about "now", "today", and
    # the freshness of any [SEARCH-RESULT] block in the same context.
    context = [_now_system_msg(), *context]
    system_prompt = _system_prompt_for_capability(capability)
    model = capability_model(capability)
    messages = make_messages(system_prompt, context, user_text)
    response = chat_once(
        messages,
        tools=None,
        use_reasoning=use_reasoning,
        model=model,
        capability=capability,
    )
    answer = (response.choices[0].message.content or "").strip()
    logger.info(
        "capability.finish chat_id=%s capability=%s answer_len=%s model=%s",
        chat_id,
        capability,
        len(answer),
        model,
    )
    return answer


def _tool_result_message(tool_call_id: str, name: str, content: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content[:20000],
    }


def _serialize_tool_result_content(value) -> str:
    if isinstance(value, NormalizedResult):
        return json.dumps(value.to_dict(), ensure_ascii=False)
    if isinstance(value, list):
        serialized = []
        for item in value:
            if isinstance(item, NormalizedResult):
                serialized.append(item.to_dict())
            else:
                serialized.append(item)
        return json.dumps(serialized, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _assistant_tool_message(message) -> dict:
    tool_calls = []
    for tool_call in getattr(message, "tool_calls", None) or []:
        tool_calls.append(
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments or "{}",
                },
            }
        )
    return {
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": tool_calls,
    }


async def run_agent(chat_id: int, user_text: str) -> str:
    query = _normalize_query(user_text)
    use_reasoning = _needs_reasoning(user_text)
    search_enabled = _search_enabled()
    logger.info(
        "agent.start chat_id=%s query_len=%s reasoning=%s search_enabled=%s",
        chat_id,
        len(query or ""),
        use_reasoning,
        search_enabled,
    )

    if not _thinking_enabled() and not search_enabled:
        logger.info(
            "agent.fallback_simple chat_id=%s reason=thinking_and_search_disabled",
            chat_id,
        )
        return await run_simple(chat_id, user_text)

    if search_enabled and _is_explicit_search_intent(user_text):
        return await run_search(chat_id, user_text, use_reasoning)

    context = await memory_manager.select_context(
        chat_id=chat_id, user_query=query, system_prompt=None
    )
    context = trim_terminal_user_duplicate(context, user_text)
    messages = make_messages(AGENT_TOOL_SYSTEM_PROMPT, context, query)
    tools = tool_spec()
    used_sources: list[dict] = []

    response = chat_once(
        messages,
        tools=tools,
        use_reasoning=use_reasoning,
        capability="agent_reasoning",
    )
    step = 0
    while step < _max_steps():
        step += 1
        logger.info("agent.step chat_id=%s step=%s", chat_id, step)
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            answer = (message.content or "").strip()
            sources_block = _format_sources(used_sources)
            if sources_block:
                answer = f"{answer}\n\nДжерела:\n{sources_block}".strip()
            if used_sources:
                await _append_search_memory_event(
                    chat_id,
                    user_text,
                    [query] if query else [],
                    used_sources,
                    answer,
                    status="agent_tool_success",
                )
            logger.info(
                "agent.finish chat_id=%s step=%s answer_len=%s sources=%s",
                chat_id,
                step,
                len(answer),
                len(used_sources),
            )
            return answer

        messages.append(_assistant_tool_message(message))
        for tool_call in tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except Exception:
                args = {}
            logger.info(
                "agent.tool_call chat_id=%s step=%s tool=%s args_keys=%s",
                chat_id,
                step,
                name,
                sorted(args.keys()),
            )

            if name == "search_web" and search_enabled:
                results = await search_web(
                    args.get("query", ""),
                    args.get("max_results"),
                    args.get("recency_days"),
                )
                used_sources.extend(results)
                logger.info(
                    "agent.tool_result chat_id=%s step=%s tool=%s results=%s",
                    chat_id,
                    step,
                    name,
                    len(results),
                )
                messages.append(
                    _tool_result_message(
                        tool_call.id, name, _serialize_tool_result_content(results)
                    )
                )
            elif name == "fetch_page" and search_enabled:
                page_text = await fetch_page(args.get("url", ""))
                logger.info(
                    "agent.tool_result chat_id=%s step=%s tool=%s text_len=%s",
                    chat_id,
                    step,
                    name,
                    len(page_text or ""),
                )
                messages.append(_tool_result_message(tool_call.id, name, page_text))
            else:
                logger.warning(
                    "agent.tool_disabled chat_id=%s step=%s tool=%s",
                    chat_id,
                    step,
                    name,
                )
                messages.append(
                    _tool_result_message(
                        tool_call.id, name, f"TOOL_ERROR: {name} is disabled or unknown"
                    )
                )

        response = chat_once(
            messages,
            tools=None,
            use_reasoning=use_reasoning,
            capability="agent_reasoning",
        )

    final = (
        response.choices[0].message.content
        or "Не вдалося завершити міркування. Дай мені ще підказку."
    )
    sources_block = _format_sources(used_sources)
    if sources_block:
        final = f"{final.strip()}\n\nДжерела:\n{sources_block}"
    if used_sources:
        await _append_search_memory_event(
            chat_id,
            user_text,
            [query] if query else [],
            used_sources,
            final,
            status="agent_tool_max_steps",
        )
    logger.warning(
        "agent.max_steps_reached chat_id=%s max_steps=%s answer_len=%s sources=%s",
        chat_id,
        _max_steps(),
        len(final.strip()),
        len(used_sources),
    )
    return final.strip()


async def run_simple(
    chat_id: int,
    user_text: str,
    *,
    capability: str = "chat_final",
    use_reasoning: bool = False,
    turn_context_msgs: list[dict] | None = None,
) -> str:
    logger.info("simple.start chat_id=%s text_len=%s", chat_id, len(user_text or ""))
    answer = await run_capability(
        chat_id,
        user_text,
        capability=capability,
        use_reasoning=use_reasoning,
        turn_context_msgs=turn_context_msgs,
    )
    logger.info("simple.finish chat_id=%s answer_len=%s", chat_id, len(answer))
    return answer
