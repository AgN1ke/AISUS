# Рішення По Імплементації Веб-Пошуку

Оновлено: 2026-04-04. Переглянуто на основі бенчмарків 2026 (`docs/research/search-stack.md`).

## Короткий Висновок

Primary search = **Brave Search API** (score 14.89, latency 669ms, $5-9/1K). Не Perplexity (score 12.96, latency 11s+, як було раніше). Extract = Tavily. Semantic/docs = Exa. Built-in LLM search = fallback only.

## Чому Змінилось Рішення

Попередній вибір Perplexity Search API як primary raw search базувався на його multi-query можливостях і conversational fit. Бенчмарки 2026 (AIMultiple, 8 API) показали:

| | Brave | Perplexity |
|---|-------|-----------|
| Agent Score | **14.89** (#1) | 12.96 (#7) |
| Latency | **669ms** | 11,000ms+ |
| Ціна/1K | $5-9 | $5 |

Brave в **16x швидший** при вищій якості. Perplexity — найповільніший серед усіх 8 провайдерів.

## Provider Stack

### 1. Primary Raw Search: Brave Search API

**Для:** `general`, `news`.

Чому:
- Найвищий agent score (14.89) серед усіх провайдерів.
- Власний індекс (30B+ сторінок), не Google/Bing залежний.
- Найнижча latency (669ms).
- Flat per-request pricing — передбачувані витрати.
- Фільтри: freshness, language, country, extra snippets.

### 2. Primary Semantic/Research: Exa Search

**Для:** `docs`, `research_paper`, technical deep search.

Чому:
- Neural embeddings — знаходить концептуально пов'язаний контент.
- Categories: news, research paper, financial report, company.
- Published/crawl date filters.
- `additionalQueries` для deep search.
- Score 14.39 (#3 в бенчмарках).

### 3. Primary Extract/Crawl: Tavily

**Для:** витягування контенту з конкретних URLs, site-focused crawl.

Чому:
- Окремі `/extract`, `/crawl`, `/map` endpoints.
- `chunks_per_source` — query-relevant chunks замість full page.
- Per-result `score` (0-1) для relevance filtering.
- Score 13.67 (#5) — не найкращий для search, але найкращий для extraction.

### 4. Cheap Fallback: Serper

**Для:** fallback коли Brave недоступний.

Чому:
- $0.30-1.00/1K — найдешевший.
- Google SERP wrapper — reliable results.
- Не дає extraction — тільки SERP.

### 5. Model-Native Search: Gemini/OpenAI/Anthropic

**Роль:** fallback / verification / fast grounded mode. **НЕ primary retrieval.**

Чому не primary:
- Model-managed search — менше контролю.
- Модель сама вирішує query, кількість запитів, синтез.
- Не підходить для explicit pipeline де planner, composer, evaluator — окремі шари.

### 6. Новий Кандидат: Firecrawl

**Score:** 14.58 (#2). **Ціна:** ~$0.83/1K. Інтегрований search + extraction.

**Статус:** не протестований. Варто оцінити як альтернативу зв'язці Brave + Tavily.

## Provider Routing Matrix

| Profile | Primary | Co-primary/Extract | Fallback |
|---------|---------|-------------------|----------|
| `general` | Brave | — | Tavily, Serper |
| `news` | Brave | Tavily (topic=news) | Serper |
| `docs` | Exa (category) | Tavily extract/crawl | Brave |
| `research_paper` | Exa (category=research paper) | — | Brave |
| `site_search` | Tavily search/crawl | — | fetch_page |

## Архітектура Pipeline

6 фаз (деталі в `implementation-roadmap.md`):

1. **Query Planner** (cheap model) → 1-3 sub-queries з profiles.
2. **Parallel Search** — sub-queries до різних провайдерів через `asyncio.gather()`.
3. **Normalize & Rank** — `NormalizedResult`, relevance scoring, dedup.
4. **Selective Extract** — snippet-first, Tavily chunks тільки для top URLs якщо snippets недостатньо.
5. **Evaluate** — per-sub-query coverage, targeted retry зі зміною стратегії.
6. **Synthesize** — capable model, ranked evidence, inline citations.

## Що Не Треба Робити

- Не робити Perplexity Sonar / OpenAI web search / Gemini grounding основним UX path.
- Не лишати глобальний `SEARCH_PROVIDER` як головну точку правди.
- Не змішувати extract, search, evaluator і synthesis в одному модулі.
- Не витягувати full page content для кожного search result.
- Не тримати один sequential fallback chain — parallel sub-queries до різних провайдерів.

## Джерела

- AIMultiple Agentic Search Benchmark 2026: https://aimultiple.com/agentic-search
- Brave Search API: https://brave.com/search/api/
- Exa Search: https://exa.ai/docs/reference/search
- Tavily Best Practices: https://docs.tavily.com/documentation/best-practices/best-practices-search
- Tavily Extract: https://docs.tavily.com/documentation/api-reference/endpoint/extract
- Firecrawl: https://www.firecrawl.dev/blog/top_web_search_api_2025
- Serper: https://serper.dev/
