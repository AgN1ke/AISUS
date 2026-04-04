# Search Flow

Оновлено: 2026-04-04.

## Поточний Пошуковий Потік

### Що Вже Працює

1. `app/message_logic.py` → planner вирішує route=search.
2. `agent/search_task.py` → `build_search_task()` будує `SearchTask` з mode, recency_days, preferred_domains.
3. Query composer може будувати query з діалогового зрізу (для "ну загугли" сценаріїв).
4. `agent/tools/web_search.py` → `search_web()` обирає провайдера по profile-based order.
5. `agent/search_task.py` → evaluator оцінює evidence, може запустити retry (max 3).
6. `agent/runner.py` → synthesis формує відповідь з evidence + sources.
7. Gemini search як grounded fallback без зовнішніх search API keys.

### Що Не Працює

1. **Один query на складне питання.** Немає decomposition на sub-queries.
2. **Sequential fallback chain.** Перший провайдер з ≥2 результатами виграє.
3. **Примітивна оцінка:** "3+ results AND 2+ domains = sufficient" без перевірки relevance.
4. **Retry не змінює стратегію:** той самий profile, ті самі провайдери, новий query.
5. **Різнорідні результати:** різні dict'и від різних провайдерів, немає нормалізації.
6. **`alternative_queries` — порожній tuple.** Ніколи не заповнюється.
7. **Кеш занадто гранулярний:** зміна будь-якого параметра = cache miss.
8. **Сторінки ріжуться на 1200 chars.** Важлива інформація втрачається.

## Цільовий Потік

```
User Query
    ↓
ФАЗА 1: QUERY PLANNER (cheap model)
  - Декомпозиція на 1-3 sub-queries
  - Profile per sub-query (general/news/docs/research/site_search)
  - Alternative formulations
  - need_extract, recency_days
    ↓
ФАЗА 2: PARALLEL SEARCH (asyncio.gather)
  - Sub-queries → різні провайдери по profile
  - general/news → Brave (669ms, score 14.89)
  - docs/research → Exa (semantic)
  - 5 results per sub-query
    ↓
ФАЗА 3: NORMALIZE & RANK
  - Кожен результат → NormalizedResult
  - Dedup по domain + title similarity
  - Relevance scoring (0-1): Tavily score as-is, інші — computed
  - Drop score < 0.5
    ↓
ФАЗА 4: SELECTIVE EXTRACT (conditional)
  - Default: НЕ запускається
  - Якщо evaluator запитав → Tavily chunks для top 2-3 URLs
  - Якщо source-first → extract одразу
    ↓
ФАЗА 5: EVALUATE
  - Per sub-query: чи є відповідь?
  - Gap → targeted retry (тільки для конкретного gap)
  - Retry 2: інший провайдер
  - Retry 3: semantic search (Exa)
  - Max 2 retries total
    ↓
ФАЗА 6: SYNTHESIZE (capable model)
  - Ranked results (lost-in-the-middle ordering)
  - User intent + style policy
  - Inline citations [1], [2]
  - НЕ бачить: planner trace, evaluator decisions
```

## Ключові Об'єкти

| Об'єкт | Де живе | Що містить |
|--------|---------|------------|
| `SearchPlan` | `agent/search_task.py` | sub_queries, original_request, needs_extract, recency_days |
| `SubQuery` | `agent/search_task.py` | query, profile, alternative, provider_hint |
| `SearchTask` | `agent/search_task.py` | Існуючий. Розширити alternative_queries |
| `NormalizedResult` | `agent/search_task.py` | url, title, snippet, relevance_score, source_provider, domain |
| `EvidencePack` | `agent/search_task.py` | results, sub_query_coverage, extraction_attempted |
| `SearchEvaluation` | `agent/search_task.py` | Існуючий. Додати retry_sub_query, coverage map |

## Як Поточний Код Мапиться На Цільовий Потік

| Цільова фаза | Поточний код | Що треба змінити |
|--------------|-------------|------------------|
| Query Planner | `build_search_task()` | Додати decomposition, заповнити `alternative_queries` |
| Parallel Search | `search_web()` sequential chain | `asyncio.gather()`, profile→provider mapping |
| Normalize | Немає | Новий: `NormalizedResult`, конвертери per provider |
| Selective Extract | `extract_search_pages()` завжди | Snippet-first, Tavily chunks, 4000 chars |
| Evaluate | `evaluate_search_step()` | Per-sub-query coverage, targeted retry |
| Synthesize | Частина `_run_direct_search()` | Isolation, lost-in-the-middle, citations |

Деталі кожної зміни — в `implementation-roadmap.md`.
