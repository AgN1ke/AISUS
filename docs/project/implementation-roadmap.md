# Дорожня Карта Імплементації

Дата: 2026-04-03

## Для Чого Цей Документ

Цей документ — не стратегія і не дослідження. Це конкретний покроковий план **що саме треба зробити в коді, в якому порядку і як**. Кожен блок описує: яку проблему вирішуємо, які файли чіпаємо, що має з'явитися на виході, які залежності від інших блоків і як перевірити результат.

Документ спирається на:

- аудит поточного коду (`docs/project/audit-baseline-2026-04-03.md`);
- оновлене дослідження пошукового стеку (`docs/research/search-stack.md`);
- routing contract (`docs/project/routing-contract.md`);
- capability matrix (`docs/project/capability-matrix.md`);
- strategy і plan (`docs/project/strategy.md`, `docs/project/plan.md`).

Блоки пронумеровані за пріоритетом. Кожен наступний блок може починатися тільки після попереднього, якщо не вказано інше.

---

## Зміст

1. [Блок 1. Розбити process_message() по шарах](#блок-1-розбити-process_message-по-шарах)
2. [Блок 2. Normalized Result і Evidence Layer](#блок-2-normalized-result-і-evidence-layer)
3. [Блок 3. Query Planner з декомпозицією](#блок-3-query-planner-з-декомпозицією)
4. [Блок 4. Parallel Search Execution](#блок-4-parallel-search-execution)
5. [Блок 5. Smart Evaluation](#блок-5-smart-evaluation)
6. [Блок 6. Selective Extract](#блок-6-selective-extract)
7. [Блок 7. Synthesis Isolation](#блок-7-synthesis-isolation)
8. [Блок 8. Retry зі зміною стратегії](#блок-8-retry-зі-зміною-стратегії)
9. [Блок 9. Кеш і Cost Management](#блок-9-кеш-і-cost-management)
10. [Блок 10. Прибрати Global State і Dead Code](#блок-10-прибрати-global-state-і-dead-code)
11. [Блок 11. Тестова Матриця](#блок-11-тестова-матриця)
12. [Черговість і Залежності](#черговість-і-залежності)
13. [Що Не Входить У Цю Дорожню Карту](#що-не-входить-у-цю-дорожню-карту)

---

## Блок 1. Розбити process_message() По Шарах

### Проблема

`app/message_logic.py` → `process_message()` — це god function (~210 рядків), яка одночасно:

- перевіряє auth;
- визначає згадки і geometry;
- викликає media routing;
- пише в пам'ять;
- вирішує, чи треба агентний режим;
- генерує фінальну відповідь;
- відправляє її в Telegram.

Routing contract (`docs/project/routing-contract.md`) описує 10 окремих шарів. У коді це все один метод. Поки цей метод не розрізано, будь-яка нова capability вростає в нього хаотично.

### Що Зробити

Розрізати `process_message()` на окремі функції з чіткими сигнатурами. Кожна функція — один шар з routing contract.

#### Крок 1.1. Виділити Access Gate

Створити окрему функцію `check_access()` в `app/message_logic.py`:

```python
async def check_access(msg: UnifiedMessage, pool) -> AccessResult:
    """
    Перевіряє auth, повертає:
    - allowed: bool
    - deny_reason: str | None
    - session_state: dict (mode, auth_status тощо)
    """
```

**Що чіпаємо:** `app/message_logic.py` — витягуємо всю auth-логіку (перевірка пароля, `is_authorized()`, `get_settings()`) в окрему функцію.

**Перевірка:** існуючі тести `tests/test_060_message_logic.py` мають продовжувати проходити. Додати unit-тест на `check_access()` окремо.

#### Крок 1.2. Виділити Task Builder

Створити `build_user_task()`:

```python
async def build_user_task(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    media_context: str | None,
) -> UserTask:
    """
    Формує задачу з нормалізованого повідомлення.
    UserTask містить:
    - instruction: str (текст запиту)
    - has_media_target: bool
    - media_type: str | None
    - media_context: str | None (опис картинки/відео)
    - needs_search_hint: bool (heuristic, не фінальне рішення)
    """
```

**Що чіпаємо:** `app/message_logic.py` — витягуємо логіку визначення типу задачі (text/media/search hint). `app/chat_geometry.py` залишається як є, тільки його результат тепер передається в `build_user_task()`.

#### Крок 1.3. Виділити Planner Call

Planner вже існує в `agent/planner.py`. Зараз він викликається всередині `process_message()`. Виділити виклик planner'а в окрему функцію:

```python
async def plan_execution(task: UserTask, session: dict) -> ExecutionPlan:
    """
    Обгортка над agent/planner.plan().
    Повертає ExecutionPlan:
    - route: str ("chat", "search", "image", "video", "voice", "document")
    - use_reasoning: bool
    - capability_model: str | None
    """
```

#### Крок 1.4. Виділити Response Sender

Створити `send_response()`:

```python
async def send_response(
    msg: UnifiedMessage,
    text: str,
    reply_to: int | None = None,
) -> None:
    """Відправка відповіді через адаптер. Форматування, split по довжині, Telegram HTML."""
```

**Що чіпаємо:** витягнути з `process_message()` всю логіку `msg.reply()`, truncation до 4096, форматування.

#### Крок 1.5. Зібрати Назад

Після виділення всіх шарів `process_message()` стає оркестратором:

```python
async def process_message(msg, pool):
    access = await check_access(msg, pool)
    if not access.allowed:
        return await send_response(msg, access.deny_reason)

    geometry = resolve_geometry(msg)
    media_ctx = await handle_media_if_needed(msg, geometry)
    task = await build_user_task(msg, geometry, media_ctx)
    plan = await plan_execution(task, access.session_state)
    result = await execute_plan(plan, task, memory_context)
    await append_to_memory(msg, result, pool)
    await send_response(msg, result.text)
```

Кожен виклик — окрема функція з типізованим входом/виходом, яку можна тестувати ізольовано.

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `app/message_logic.py` | Розбивається на 5+ окремих функцій |
| `tests/test_060_message_logic.py` | Додаються тести на кожну виділену функцію |

### Залежності

Ніяких. Це першочерговий блок, який розблоковує всі наступні.

### Критерій Готовності

- `process_message()` < 50 рядків (оркестрація).
- Кожен виділений шар має хоча б один unit-тест.
- `pytest -q` зелений.
- Live smoke-test: бот відповідає текстом, пошуком і на медіа.

---

## Блок 2. Normalized Result І Evidence Layer

### Проблема

Різні search-провайдери повертають різні поля:

- Bing: `name`, `url`, `snippet`
- Serper: `title`, `link`, `snippet`
- Tavily: `title`, `url`, `content` / `raw_content`, `score`
- Exa: `title`, `url`, `summary` / `highlights` / `text`
- Gemini grounding: `title`, `uri`, `snippet` (з `groundingMetadata`)
- Perplexity: `title`, `url`, `snippet` (з `results`)

Зараз кожен провайдер в `agent/tools/web_search.py` формує `dict` зі своїми ключами. Evaluator і synthesis бачать різнорідні дані. Scoring нестабільний — порівнюються яблука з апельсинами.

### Що Зробити

#### Крок 2.1. Створити NormalizedResult dataclass

Нове місце: `agent/search_types.py` (або розширити існуючий `agent/search_task.py`).

```python
@dataclass(frozen=True)
class NormalizedResult:
    url: str
    title: str
    snippet: str              # уніфіковано з content/summary/highlights
    relevance_score: float    # 0.0–1.0
    source_provider: str      # "brave", "tavily", "exa", ...
    published_date: str | None
    domain: str               # витягнутий з URL
    has_full_content: bool    # чи витягнуто повний текст
    full_content: str | None  # повний текст (якщо витягнуто)
```

#### Крок 2.2. Створити EvidencePack dataclass

```python
@dataclass
class EvidencePack:
    results: list[NormalizedResult]  # ранжовані, дедупліковані
    sub_query_coverage: dict[str, bool]  # per sub-query: чи знайшли відповідь
    total_providers_used: int
    total_results_before_filter: int
    extraction_attempted: bool
```

#### Крок 2.3. Написати конвертери для кожного провайдера

В `agent/tools/web_search.py` кожна `_search_*` функція зараз повертає `list[dict]`. Додати конвертер після кожного провайдера:

```python
def _normalize_brave_result(raw: dict, query: str) -> NormalizedResult:
    return NormalizedResult(
        url=raw["url"],
        title=raw.get("title", ""),
        snippet=raw.get("description", raw.get("extra_snippets", [""])[0]),
        relevance_score=_compute_relevance(raw, query),
        source_provider="brave",
        published_date=raw.get("page_age"),
        domain=_extract_domain(raw["url"]),
        has_full_content=False,
        full_content=None,
    )
```

Аналогічно для: `_normalize_tavily_result`, `_normalize_exa_result`, `_normalize_serper_result`, `_normalize_bing_result`, `_normalize_gemini_result`, `_normalize_perplexity_result`, `_normalize_openai_result`.

**Tavily вже дає `score`** — використовувати його як є. Для решти — обчислювати `_compute_relevance()` на основі: query term overlap (0–0.4) + snippet length score (0–0.2) + preferred domain bonus (0–0.2) + recency bonus (0–0.2).

#### Крок 2.4. Замінити downstream код

Все що після `search_web()` — evaluator, synthesis — тепер працює з `list[NormalizedResult]` замість `list[dict]`.

`_filter_and_rank_results()` в `web_search.py` переписати на NormalizedResult. Dedup по `(domain, title[:50])`. Sort по `relevance_score` descending.

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `agent/search_task.py` | Додаються `NormalizedResult`, `EvidencePack` dataclasses |
| `agent/tools/web_search.py` | Кожен провайдер отримує `_normalize_*` конвертер. `search_web()` повертає `list[NormalizedResult]` |
| `agent/runner.py` | `_run_direct_search()` працює з `NormalizedResult` замість `dict` |
| `tests/test_034_web_search.py` | Тести оновлені під нові типи |

### Залежності

Незалежний від Блоку 1. Можна робити паралельно.

### Критерій Готовності

- Все що після `search_web()` бачить тільки `NormalizedResult`.
- Кожен провайдер має `_normalize_*` функцію з тестом.
- `relevance_score` для Tavily = score від API, для решти = computed.
- `pytest -q` зелений.

---

## Блок 3. Query Planner З Декомпозицією

### Проблема

Зараз `build_search_task()` в `agent/search_task.py` (872 рядки) будує **один query** з одного user message. Складне питання типу "як нові санкції ЄС вплинуть на ціни газу" йде як один запит. Поле `alternative_queries` в `SearchTask` існує, але **ніколи не заповнюється** (завжди `tuple()`).

За дослідженням: Azure AI Search генерує в середньому **3 sub-queries per query plan**. Query decomposition — це single biggest impact improvement для якості пошуку.

### Що Зробити

#### Крок 3.1. Створити Search Query Planner

Нова функція в `agent/search_task.py`:

```python
async def plan_search_queries(
    user_text: str,
    dialogue_excerpt: list[dict],  # останні 6 повідомлень
    mode_hint: str | None = None,
) -> SearchPlan:
    """
    Декомпозує запит на 1-3 focused sub-queries.
    Використовує cheap model (gpt-4o-mini).
    """
```

`SearchPlan` dataclass:

```python
@dataclass(frozen=True)
class SearchPlan:
    sub_queries: tuple[SubQuery, ...]   # 1-3 штуки
    original_request: str
    needs_extract: bool
    recency_days: int | None

@dataclass(frozen=True)
class SubQuery:
    query: str
    profile: str          # "general", "news", "docs", "research_paper", "site_search"
    alternative: str | None  # альтернативне формулювання
    provider_hint: str | None  # "brave", "exa", "tavily" (suggestion, not mandate)
```

#### Крок 3.2. Промпт для Query Planner

Додати в `core/prompts.py`:

```python
SEARCH_QUERY_PLANNER_PROMPT = """Ти — планувальник пошукових запитів. Твоя задача — розбити складне питання на 1-3 focused пошукові sub-queries.

Правила:
1. Якщо питання просте і конкретне — поверни 1 sub-query.
2. Якщо питання складене (A і B, A vs B, причина + наслідок) — розбий на 2-3 sub-queries.
3. Кожен sub-query повинен бути self-contained і шукати конкретну інформацію.
4. Для кожного sub-query визнач profile: general, news, docs, research_paper, site_search.
5. Якщо є контекст розмови — використай його для disambiguation.
6. Для кожного sub-query запропонуй одне альтернативне формулювання.

Відповідай JSON:
{
  "sub_queries": [
    {"query": "...", "profile": "...", "alternative": "..."},
    ...
  ],
  "needs_extract": false,
  "recency_days": null
}"""
```

**Модель:** gpt-4o-mini (або еквівалент cheap model через provider registry). Дорога модель — тільки для synthesis.

#### Крок 3.3. Інтегрувати з build_search_task()

`build_search_task()` тепер:

1. Спочатку викликає `plan_search_queries()` — отримує `SearchPlan` з 1-3 sub-queries.
2. Для кожного sub-query будує `SearchTask` (вже існуючий dataclass).
3. Нарешті заповнює `alternative_queries` з `SubQuery.alternative`.
4. Повертає `list[SearchTask]` замість одного `SearchTask`.

Fallback: якщо LLM planner впав — будувати один `SearchTask` як раніше (heuristic path). Ніколи не блокувати пошук через помилку planner'а.

#### Крок 3.4. Оновити runner

`_run_direct_search()` в `agent/runner.py` тепер отримує `list[SearchTask]` і обробляє їх через паралельний search (Блок 4). Якщо Блок 4 ще не готовий — обробляє послідовно.

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `agent/search_task.py` | Додається `SearchPlan`, `SubQuery`, `plan_search_queries()` |
| `core/prompts.py` | Додається `SEARCH_QUERY_PLANNER_PROMPT` |
| `agent/runner.py` | `_run_direct_search()` приймає `list[SearchTask]` |
| `tests/test_032_search_task.py` | Тести на decomposition |

### Залежності

Залежить від Блоку 2 (NormalizedResult), бо результати sub-queries будуть мержитися.

### Критерій Готовності

- Складне питання (з "і", "vs", "причина + наслідок") генерує 2-3 sub-queries.
- Просте питання генерує 1 sub-query.
- `alternative_queries` в `SearchTask` заповнюється.
- Fallback працює якщо LLM planner недоступний.
- `pytest -q` зелений.

---

## Блок 4. Parallel Search Execution

### Проблема

Зараз в `agent/tools/web_search.py` → `search_web()` провайдери пробуються **послідовно** як fallback chain. Перший, хто дав ≥2 результати (`minimum_acceptable`), виграє — навіть якщо результати нерелевантні. Усі sub-queries з Блоку 3 пішли б через один і той самий sequential chain.

За дослідженням: scatter-gather pattern (паралельні sub-queries до різних провайдерів + консолідація) — це правильний підхід. Загальна latency = max(individual) замість sum.

### Що Зробити

#### Крок 4.1. Profile-to-Provider Mapping

Створити явний mapping в `agent/tools/web_search.py`:

```python
PROFILE_PRIMARY_PROVIDER: dict[str, str] = {
    "general": "brave_search",
    "news": "brave_search",
    "docs": "exa_search",
    "research_paper": "exa_search",
    "site_search": "tavily",
}
```

Це замінює поточний `PROFILE_DEFAULT_ORDERS` з довгими fallback chains. Primary provider обирається per sub-query за profile.

Залишити fallback chain, але коротший: primary → один fallback → stop.

#### Крок 4.2. Паралельний Запуск Sub-Queries

В `agent/runner.py`, `_run_direct_search()`:

```python
async def _collect_all_evidence(tasks: list[SearchTask]) -> EvidencePack:
    # Кожен sub-query → свій провайдер → паралельно
    coros = [_search_single_task(task) for task in tasks]
    raw_results = await asyncio.gather(*coros, return_exceptions=True)

    # Merge + dedup + rank
    all_results: list[NormalizedResult] = []
    for batch in raw_results:
        if isinstance(batch, Exception):
            log.warning("Sub-query failed: %s", batch)
            continue
        all_results.extend(batch)

    deduped = _deduplicate(all_results)
    ranked = sorted(deduped, key=lambda r: r.relevance_score, reverse=True)
    return EvidencePack(results=ranked, ...)
```

#### Крок 4.3. Провайдер-Specific Timeout

Замінити поточні inconsistent timeouts:

```python
PROVIDER_TIMEOUTS: dict[str, float] = {
    "brave_search": 8.0,
    "serper": 5.0,
    "exa_search": 8.0,
    "tavily": 12.0,
    "perplexity_search": 20.0,
    "openai_search": 15.0,
    "gemini_search": 15.0,
    "bing": 8.0,
    "bing_html": 10.0,
    "ddg": 10.0,
}
```

Rationale: fast providers (Brave 669ms avg, Serper fast) = 5-8s. Medium (Tavily 400-1200ms) = 12s. Slow (Perplexity 11s+ avg) = 20s.

#### Крок 4.4. Deduplication

Зараз dedup по `(url, title)`. Додати similarity check:

```python
def _deduplicate(results: list[NormalizedResult]) -> list[NormalizedResult]:
    seen: set[str] = set()
    out: list[NormalizedResult] = []
    for r in results:
        key = r.domain + "|" + r.title[:50].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
```

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `agent/tools/web_search.py` | `PROFILE_PRIMARY_PROVIDER`, скорочений fallback chain, timeouts |
| `agent/runner.py` | `_collect_all_evidence()` з `asyncio.gather()` |
| `agent/search_task.py` | `SubQuery.provider_hint` впливає на вибір провайдера |

### Залежності

Залежить від Блоку 2 (NormalizedResult) і Блоку 3 (list[SearchTask]).

### Критерій Готовності

- 2 sub-queries виконуються паралельно (видно по логам — latency ≈ max а не sum).
- Різні profiles → різні primary providers.
- Failure одного sub-query не блокує інші.
- `pytest -q` зелений.

---

## Блок 5. Smart Evaluation

### Проблема

Heuristic evaluator в `agent/search_task.py` → `_heuristic_search_evaluation()` вважає: "3+ результати AND 2+ distinct domains = sufficient". Це не перевіряє relevance. Три сміттєвих результати з двох доменів проходять.

LLM evaluator бачить тільки top 5 results (snippet по 500 chars) і top 2 pages (по 1200 chars). Він може прийняти або відхилити, але не вміє оцінювати **per sub-query coverage**.

### Що Зробити

#### Крок 5.1. Per-Sub-Query Coverage Check

Evaluator тепер знає про sub-queries з `SearchPlan`:

```python
async def evaluate_evidence(
    plan: SearchPlan,
    evidence: EvidencePack,
    attempt: int,
) -> SearchEvaluation:
    """
    Перевіряє:
    1. Чи є хоча б 1 result з relevance_score >= 0.5 для КОЖНОГО sub-query
    2. Якщо gap знайдено — повертає конкретний sub-query для retry
    """
```

#### Крок 5.2. Heuristic з Relevance Score

Замінити "3 results + 2 domains" на:

```python
def _heuristic_evaluation(evidence: EvidencePack) -> HeuristicResult:
    high_relevance = [r for r in evidence.results if r.relevance_score >= 0.5]
    if len(high_relevance) >= 3:
        return HeuristicResult(sufficient=True)
    if len(high_relevance) >= 1 and evidence.extraction_attempted:
        return HeuristicResult(sufficient=True)
    return HeuristicResult(sufficient=False, gap="low relevance results")
```

#### Крок 5.3. LLM Evaluator з Повним Контекстом

Збільшити вхід для LLM evaluator:

- Top 8 results (замість 5) з relevance_score.
- Top 3 pages (замість 2) по 2000 chars (замість 1200).
- Список sub-queries з плану — щоб evaluator міг перевірити coverage кожного.

Оновити `SEARCH_EVALUATOR_SYSTEM_PROMPT` в `core/prompts.py`:

```
Ти оцінюєш чи зібраних результатів достатньо для відповіді на кожну частину запиту.

Для кожного sub-query відповідай:
- covered: bool
- best_source: url або null

Якщо хоча б один sub-query не covered — вкажи retry_query саме для нього.
```

#### Крок 5.4. Targeted Retry

Замість generic retry (новий query для всього запиту) — retry тільки для конкретного gap:

```python
@dataclass
class SearchEvaluation:
    sufficient: bool
    should_retry: bool
    retry_sub_query: SubQuery | None  # конкретний sub-query для retry
    retry_reason: str | None
    coverage: dict[str, bool]  # per sub-query coverage map
```

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `agent/search_task.py` | `evaluate_evidence()`, coverage-based heuristic, targeted retry |
| `core/prompts.py` | Оновлений `SEARCH_EVALUATOR_SYSTEM_PROMPT` |
| `agent/runner.py` | Retry loop працює з targeted `retry_sub_query` |
| `tests/test_038_search_evaluator.py` | Тести на coverage-based evaluation |

### Залежності

Залежить від Блоку 2 (NormalizedResult з relevance_score), Блоку 3 (SearchPlan з sub-queries).

### Критерій Готовності

- Evaluator перевіряє coverage per sub-query.
- 3 нерелевантних результати (score < 0.3) не проходять як "sufficient".
- Retry відбувається тільки для конкретного gap, не для всього запиту.
- `pytest -q` зелений.

---

## Блок 6. Selective Extract

### Проблема

Зараз якщо `need_extract=True` — витягуються сторінки для всіх top URLs. `extract_search_pages()` в `web_search.py` бере max_pages URLs і витягує через Tavily extract → fallback fetch_page. Це:

- Повільно (кожен URL = окремий API call).
- Дорого (Tavily extract = окремий кредит per URL).
- Часто марно (snippets достатньо для відповіді на більшість питань).
- Сторінки ріжуться на 1200 chars в synthesis — важлива інформація втрачається.

### Що Зробити

#### Крок 6.1. Snippet-First Policy

За замовчуванням extraction **не запускається**. Тільки якщо:

1. Evaluator (Блок 5) визнав snippets "insufficient" І вказав конкретні URLs для extract.
2. Або задача source-first (`need_primary_source=True` або profile=docs).
3. Або `need_extract=True` з SearchPlan.

#### Крок 6.2. Tavily Chunks Замість Full Page

Замінити `_extract_with_tavily()` на Tavily `chunks_per_source`:

```python
async def extract_chunks(urls: list[str], query: str) -> list[NormalizedResult]:
    """
    Витягує query-relevant chunks з URLs через Tavily.
    Повертає NormalizedResult з has_full_content=True і full_content=chunks.
    """
    response = await tavily_client.extract(
        urls=urls,
        # Якщо API підтримує chunks:
        extract_depth="advanced",
    )
    # Оновити NormalizedResult для цих URLs
```

Tavily `chunks_per_source` повертає тільки релевантні до query фрагменти замість full page. Це оптимальний middle ground.

#### Крок 6.3. Збільшити Ліміт Для Synthesis

Замінити хардкод 1200 chars per page в runner на динамічний:

```python
MAX_SNIPPET_CHARS = 500
MAX_EXTRACT_CHARS = 4000  # замість 1200
MAX_TOTAL_EVIDENCE_CHARS = 12000
```

Розподіляти бюджет: якщо 3 extracted pages — кожна отримує `MAX_TOTAL_EVIDENCE_CHARS / 3`.

#### Крок 6.4. fetch_page як Крайній Fallback

`agent/tools/fetch_page.py` залишається, але:

- Використовується **тільки** якщо Tavily extract недоступний.
- Додати User-Agent rotation (зараз один захардкожений).
- Додати timeout 10s (зараз немає explicit timeout).

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `agent/tools/web_search.py` | `extract_chunks()`, snippet-first policy |
| `agent/runner.py` | Динамічний char budget, extract тільки по evaluator request |
| `agent/tools/fetch_page.py` | Timeout, User-Agent rotation |

### Залежності

Залежить від Блоку 5 (evaluator вирішує коли extract потрібен).

### Критерій Готовності

- Default: extraction не запускається.
- Evaluator може запросити extract для конкретних URLs.
- Extracted content до 4000 chars per page (замість 1200).
- `fetch_page` використовується тільки як fallback.

---

## Блок 7. Synthesis Isolation

### Проблема

Зараз synthesis в `agent/runner.py` (`_run_direct_search()`, рядки 380-408) бачить:

- Original user request.
- Final search query.
- Top 5 results (500 chars snippets).
- Top 2 pages (1200 chars).
- Optional note якщо evidence insufficient.

Він також бачить весь dialogue context з memory. Немає чіткої межі між тим, що synthesis повинен бачити (evidence + user intent) і тим, що він НЕ повинен бачити (planner trace, query composer reasoning, evaluator decisions).

### Що Зробити

#### Крок 7.1. Побудувати Synthesis Input

Synthesis отримує чітко визначений input:

```python
@dataclass
class SynthesisInput:
    user_intent: str              # original user request
    evidence: EvidencePack        # ranked NormalizedResults
    style_policy: str             # persona/style prompt
    dialogue_context: list[dict]  # recent memory (для tone/continuity)
    # НЕ включає: planner trace, query composer reasoning,
    # evaluator decisions, provider routing details
```

#### Крок 7.2. Lost-in-the-Middle Ordering

Перед передачею evidence в synthesis — reorder:

```python
def reorder_for_llm(results: list[NormalizedResult]) -> list[NormalizedResult]:
    """
    Найрелевантніші — першими і останніми.
    Менш релевантні — в середину.
    LLM зважують початок і кінець промпту більше ніж середину.
    """
    if len(results) <= 2:
        return results
    best = results[0]
    second_best = results[1]
    middle = results[2:-1] if len(results) > 3 else []
    last = results[-1] if len(results) > 2 else second_best
    return [best] + middle + [last]
```

#### Крок 7.3. Оновити Synthesis Prompt

В `core/prompts.py` оновити `SEARCH_SYNTHESIS_SYSTEM_PROMPT`:

- Явно вказати що джерела ранжовані по релевантності.
- Вимагати inline citations `[1]`, `[2]` з посиланнями.
- Заборонити згадувати internal search process.
- Вимагати відповідь під стиль бота (persona prompt).

#### Крок 7.4. Source Attribution

Замість поточного "append sources block" — вбудувати citations в synthesis prompt:

```
Evidence:
[1] Title — url (relevance: 0.92)
    Snippet text...
[2] Title — url (relevance: 0.87)
    Snippet text...

При цитуванні використовуй формат [1], [2] тощо.
```

Synthesis model бачить пронумеровані джерела і може посилатися на них в тексті.

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `agent/runner.py` | `SynthesisInput`, `reorder_for_llm()`, synthesis isolation |
| `core/prompts.py` | Оновлений `SEARCH_SYNTHESIS_SYSTEM_PROMPT` |

### Залежності

Залежить від Блоку 2 (NormalizedResult), бажано після Блоку 6 (extract).

### Критерій Готовності

- Synthesis НЕ бачить planner/evaluator trace.
- Evidence відсортований за lost-in-the-middle pattern.
- Citations у фінальній відповіді.
- `pytest -q` зелений.

---

## Блок 8. Retry Зі Зміною Стратегії

### Проблема

Зараз retry loop в `agent/runner.py` (рядки 272-338):

```
for attempt in range(1, max_iterations + 1):
    results = search(current_query)  # ті самі провайдери, той самий profile
    evaluation = evaluate(results)
    if evaluation.sufficient: break
    current_query = evaluation.retry_query  # тільки query змінюється
```

Кожен retry — це "новий query, ті самі провайдери, той самий тип пошуку". Якщо провайдер не підходить для цього типу запиту — скільки не retry, результати будуть погані.

### Що Зробити

#### Крок 8.1. Retry Strategy Escalation

Визначити стратегію escalation:

```python
RETRY_STRATEGIES = [
    # Attempt 1: default — primary provider, original query
    # (handled by normal flow, not retry)

    # Attempt 2: reformulated query + different provider
    RetryStrategy(
        change_query=True,
        change_provider=True,
        provider_preference="next_in_fallback",
    ),

    # Attempt 3: broader/narrower query + semantic search (Exa)
    RetryStrategy(
        change_query=True,
        change_provider=True,
        provider_preference="exa_search",  # semantic замість keyword
        broaden_query=True,
    ),
]
```

#### Крок 8.2. Оновити Retry Loop

```python
async def _retry_search(
    failed_sub_query: SubQuery,
    attempt: int,
    previous_results: list[NormalizedResult],
) -> list[NormalizedResult]:
    strategy = RETRY_STRATEGIES[attempt - 2]  # attempt 2 → index 0

    # Reformulate query
    if strategy.change_query:
        new_query = failed_sub_query.alternative or await reformulate(...)

    # Switch provider
    if strategy.change_provider:
        provider = strategy.provider_preference or next_fallback(...)

    # Execute
    return await search_web(new_query, provider=provider, ...)
```

#### Крок 8.3. Track Attempted Strategies

Зберігати не тільки attempted queries (як зараз), а й attempted (query, provider) pairs:

```python
attempted: set[tuple[str, str]] = set()  # (query_lower, provider)
```

Це запобігає тому щоб retry пробував ту саму комбінацію query+provider двічі.

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `agent/runner.py` | Retry strategy escalation, provider switching |
| `agent/search_task.py` | `RetryStrategy` dataclass |

### Залежності

Залежить від Блоків 4 (parallel search) і 5 (targeted evaluation).

### Критерій Готовності

- Retry 2 використовує інший провайдер ніж retry 1.
- Retry 3 переключається на semantic search (Exa) якщо keyword search не дав результатів.
- Одна і та ж комбінація query+provider не пробується двічі.
- Max 2 retries (3 attempts total), як і раніше.

---

## Блок 9. Кеш І Cost Management

### Проблема

1. **Cache key занадто гранулярний:** `profile|mode|recency|allow|deny|country|languages|query`. Зміна будь-якого параметра = cache miss. "Новини про Apple" і "Latest Apple news" = два різних cache keys.

2. **`datetime.utcnow()` deprecated** з Python 3.12 (`db/search_repository.py`).

3. **Немає cost tracking:** кожен retry може викликати кілька провайдерів, немає моніторингу API calls.

4. **Inconsistent TTL:** search cache = 30 min, page cache = 24 hours.

### Що Зробити

#### Крок 9.1. Нормалізація Cache Key

Перед хешуванням query:

```python
def normalize_cache_query(query: str) -> str:
    """Lowercase, strip punctuation, sort words."""
    words = re.sub(r'[^\w\s]', '', query.lower()).split()
    return ' '.join(sorted(set(words)))
```

Cache key спрощується:

```python
cache_key = f"v3|{profile}|{normalize_cache_query(query)}"
```

Прибрати з key: `mode`, `recency`, `allow`, `deny`, `country`, `languages`. Ці параметри змінюються часто і роблять кеш марним.

#### Крок 9.2. Виправити datetime.utcnow()

В `db/search_repository.py`:

```python
# Було:
datetime.utcnow()

# Стало:
from datetime import datetime, timezone
datetime.now(timezone.utc)
```

#### Крок 9.3. Cost Logging

Додати counter в `agent/tools/web_search.py`:

```python
import logging
_search_log = logging.getLogger("smartest.search.cost")

async def search_web(...):
    # ...після кожного API call:
    _search_log.info(
        "search_api_call provider=%s query=%r results=%d latency_ms=%d",
        provider, query, len(results), elapsed_ms,
    )
```

Не потрібна складна система — просто structured logging для аналізу.

#### Крок 9.4. Вирівняти TTL

```python
SEARCH_CACHE_TTL_MIN = 60   # було 30 — збільшити для зменшення API calls
PAGE_CACHE_TTL_MIN = 1440   # залишити 24h
```

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `agent/tools/web_search.py` | Нормалізація cache key, cost logging |
| `db/search_repository.py` | `datetime.utcnow()` → `datetime.now(timezone.utc)` |

### Залежності

Незалежний. Можна робити паралельно з іншими блоками.

### Критерій Готовності

- "Новини Apple" і "новини apple" = один cache key.
- `datetime.utcnow()` ніде в коді.
- В логах видно кожен API call з provider, query, result count, latency.

---

## Блок 10. Прибрати Global State І Dead Code

### Проблема

1. **Global LLM clients** в `agent/llm.py`: `_client: Optional[OpenAI] = None`, `_clients: dict = {}`. Shared mutable global state.

2. **Dead code:**
   - `src/chat_history_manager.py` — in-memory history, не інтегрований.
   - `commands/admin.py` — стаби `/mem`, `/health`, не працюють.
   - `knowledge/glossary.py` — вимкнено за замовчуванням (`GLOSSARY_ENABLE_SUGGESTIONS=0`).
   - `knowledge/threads.py` — не викликається в main flow.

3. **Дублювання:** `SEARCH_TRIGGER_PATTERNS` живуть і в `runner.py`, і в `planner.py`.

### Що Зробити

#### Крок 10.1. Dependency Injection для LLM Clients

Замість global `_client`/`_clients` — створити factory function:

```python
def get_llm_client(provider: str, api_key: str) -> OpenAI | Any:
    """Повертає клієнт для провайдера. Може кешувати per-key."""
    # Кешування per (provider, api_key) — це ок, бо ключі стабільні
    # Але НЕ глобальна змінна без параметрів
```

Це не повний DI framework — просто прибрати implicit global state.

#### Крок 10.2. Видалити Dead Code

Файли до видалення (або переміщення в `_archive/`):

| Файл | Причина |
|------|---------|
| `src/chat_history_manager.py` | Не інтегрований, замінений `memory/manager.py` |
| `commands/admin.py` | Стаби без реалізації |
| `knowledge/threads.py` | Не викликається ніде |
| `encode_to_base64.py` | Utility script, не частина runtime |
| `whisper_tool.py` | Заглушка в корені, дублює `media/` |

`knowledge/glossary.py` — залишити, але позначити як disabled. Може знадобитися пізніше.

#### Крок 10.3. Централізувати Дублікати

`SEARCH_TRIGGER_PATTERNS` — один source of truth в `core/prompts.py` або `agent/search_task.py`. `planner.py` і `runner.py` імпортують звідти.

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `agent/llm.py` | Factory function замість global state |
| `src/chat_history_manager.py` | Видалити |
| `commands/admin.py` | Видалити |
| `knowledge/threads.py` | Видалити |
| `encode_to_base64.py` | Видалити |
| `whisper_tool.py` | Видалити |
| `agent/runner.py`, `agent/planner.py` | Централізувати `SEARCH_TRIGGER_PATTERNS` |

### Залежності

Незалежний. Можна робити будь-коли.

### Критерій Готовності

- Немає `_client = None` / `_clients = {}` в `agent/llm.py`.
- Видалені файли не імпортуються ніде.
- `SEARCH_TRIGGER_PATTERNS` визначено в одному місці.
- `pytest -q` зелений.

---

## Блок 11. Тестова Матриця

### Проблема

Поточні тести (20 файлів) покривають окремі модулі mock'ами. Але критичні end-to-end шляхи не тестуються:

- Decomposition → parallel search → merge → evaluate → retry → synthesis.
- Memory compression під навантаженням.
- Provider failover (один впав → інший підхопив).
- Edge cases: LLM повертає невалідний JSON, provider timeout, порожні результати.

### Що Зробити

#### Крок 11.1. Search E2E Test (mock providers)

```python
@pytest.mark.asyncio
async def test_search_e2e_decomposition():
    """Складне питання → 2 sub-queries → parallel search → merge → evaluate → sufficient."""
    with mock_providers(brave=MOCK_RESULTS_SANCTIONS, exa=MOCK_RESULTS_GAS):
        result = await run_search("як санкції ЄС вплинуть на ціни газу")
        assert len(result.evidence.results) >= 3
        assert result.evidence.sub_query_coverage["sanctions"] == True
        assert result.evidence.sub_query_coverage["gas prices"] == True
```

#### Крок 11.2. Retry Scenario Test

```python
@pytest.mark.asyncio
async def test_search_retry_changes_provider():
    """Перша спроба = 0 results → retry з іншим провайдером → success."""
    with mock_providers(brave=EMPTY, tavily=MOCK_RESULTS):
        result = await run_search("щось дуже специфічне")
        assert result.evidence.total_providers_used >= 2
```

#### Крок 11.3. LLM Failure Scenarios

```python
@pytest.mark.asyncio
async def test_query_planner_fallback_on_invalid_json():
    """LLM planner повертає невалідний JSON → fallback на heuristic."""
    with mock_llm(response="not json at all"):
        tasks = await plan_search_queries("простий запит", [])
        assert len(tasks.sub_queries) == 1  # fallback = один query

@pytest.mark.asyncio
async def test_evaluator_fallback_on_llm_failure():
    """LLM evaluator timeout → heuristic evaluation."""
    with mock_llm(timeout=True):
        eval = await evaluate_evidence(plan, evidence, attempt=1)
        assert eval is not None  # heuristic fallback worked
```

#### Крок 11.4. Live Smoke Test Matrix

Не автоматизований, але документований checklist:

| Сценарій | Очікуваний результат |
|----------|---------------------|
| Простий factual: "хто президент Франції" | 1 sub-query, fast response |
| Складний compound: "порівняй iPhone 16 і Samsung S25" | 2 sub-queries, parallel |
| News: "що нового про Ілона Маска" | news profile, recent results |
| Follow-up: "ну загугли" (після обговорення теми) | Query з dialogue context |
| Перевірка твердження: "чи правда що..." | general profile, source-first за потреби |
| Docs: "документація по FastAPI middleware" | docs profile → Exa |
| Provider failover: вимкнути Brave API key | Fallback на Tavily/Serper |
| Edge: порожній query | Graceful error, не crash |

### Файли Що Змінюються

| Файл | Що відбувається |
|------|-----------------|
| `tests/test_032_search_task.py` | Тести на decomposition |
| `tests/test_034_web_search.py` | Provider-specific tests оновлені |
| `tests/test_038_search_evaluator.py` | Coverage-based evaluation тести |
| Новий: `tests/test_040_search_e2e.py` | E2E search scenarios |

### Залежності

Після всіх інших блоків (тестує фінальну систему).

---

## Черговість І Залежності

```
Паралельна група A (незалежні):
  ├── Блок 1: Розбити process_message()
  ├── Блок 2: NormalizedResult
  ├── Блок 9: Кеш і Cost
  └── Блок 10: Dead Code

Послідовний ланцюг B (після Блоку 2):
  Блок 2 → Блок 3 (Query Planner)
         → Блок 4 (Parallel Search)
         → Блок 5 (Smart Evaluation)
         → Блок 6 (Selective Extract)
         → Блок 7 (Synthesis Isolation)
         → Блок 8 (Retry Strategy)

Фінальний:
  Блок 11: Тестова Матриця (після всіх)
```

**Оптимальний порядок виконання:**

| Фаза | Блоки | Чому |
|------|-------|------|
| **Фаза 1** | 1 + 2 + 9 + 10 (паралельно) | Чотири незалежних блоки, кожен покращує codebase без залежностей |
| **Фаза 2** | 3 (Query Planner) | Потребує NormalizedResult з Блоку 2 |
| **Фаза 3** | 4 + 5 (паралельно) | Parallel search і evaluation можна робити одночасно |
| **Фаза 4** | 6 + 7 (паралельно) | Extract і synthesis isolation незалежні |
| **Фаза 5** | 8 (Retry Strategy) | Потребує evaluation і parallel search |
| **Фаза 6** | 11 (Тестова Матриця) | Тестує все разом |

Між фазами — deploy на staging, smoke-test, pytest зелений.

---

## Що Не Входить У Цю Дорожню Карту

Ця дорожня карта покриває Етапи 3 і 3a (capability split + search orchestration). Наступні етапи документуються окремо:

| Тема | Чому не зараз | Де задокументовано |
|------|---------------|-------------------|
| Telegram event normalization (Етап 4) | Потребує стабільного routing contract | `docs/project/routing-contract.md` |
| Multimodal pipelines (Етап 5) | Потребує capability boundaries | `docs/project/capability-matrix.md` |
| Memory redesign (Етап 6) | Потребує сесії і Telegram context | `docs/project/strategy.md` |
| Admin control plane (Етап 7) | Потребує стабільних capability bindings | `docs/project/plan.md` |
| `autocommit=True` і transaction management | Infra concern, не блокує search | — |
| Broad `except Exception` cleanup | Quality concern, не блокує search | — |
| Type hints coverage | Quality concern, можна робити інкрементально | — |
| Token counting accuracy (`core/tokens.py`) | Важливо, але окремий scope | — |
