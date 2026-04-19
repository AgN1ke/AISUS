# Пошуковий Стек: Повне Дослідження

Огляд актуальний на 2026-04-03. Оновлено після аналізу індустріальних бенчмарків, офіційних документацій провайдерів, production-досвіду великих agent frameworks і academic research.

---

## Зміст

1. [Проблема, Яку Ми Розв'язуємо](#проблема-яку-ми-розвязуємо)
2. [Як Великі Фреймворки Реалізують Пошук](#як-великі-фреймворки-реалізують-пошук)
3. [Провайдери Пошуку: Порівняння З Числами](#провайдери-пошуку-порівняння-з-числами)
4. [Архітектурні Паттерни Для Агентного Пошуку](#архітектурні-паттерни-для-агентного-пошуку)
5. [Anti-Patterns: Що Точно Не Треба Робити](#anti-patterns-що-точно-не-треба-робити)
6. [Практичні Деталі Імплементації](#практичні-деталі-імплементації)
7. [Рекомендована Архітектура Для Smartest](#рекомендована-архітектура-для-smartest)
8. [Джерела](#джерела)

---

## Проблема, Яку Ми Розв'язуємо

У поточному боті пошук вже не є "прихованою магією моделі" — він винесений у окремий pipeline з `SearchTask`, evaluator і retry-loop. Але архітектурно він все ще працює як **"один запит → один провайдер → оцінка → може retry з іншим query"**. Це створює конкретні проблеми:

### Що Саме Не Працює

1. **Один запит на складне питання.** Користувач запитує "як нові санкції ЄС вплинуть на ціни газу" — і це йде в один пошуковий query. А треба було б два: `"EU sanctions Russia 2026 latest"` і `"EU sanctions impact gas prices Europe"`.

2. **Провайдери пробуються послідовно як fallback chain.** Перший, хто дав ≥2 результати, виграє — навіть якщо результати нерелевантні. Замість того щоб обрати провайдера під тип задачі.

3. **Оцінка якості примітивна.** Heuristic evaluator вважає "3+ результати з 2+ доменів = достатньо" без перевірки, чи результати взагалі відповідають на питання.

4. **Retry не змінює стратегію.** Кожна спроба — це новий query до тих самих провайдерів у тому самому порядку. Немає зміни провайдера, типу пошуку або extraction strategy.

5. **Результати від різних провайдерів мають різну структуру.** Bing дає `name/snippet`, Tavily — `title/content`, Exa — `summary/highlights`. Все йде в модель як є, без нормалізації.

6. **`alternative_queries` оголошено в SearchTask, але ніколи не заповнюється.** Поле-заглушка.

7. **Кеш занадто гранулярний.** Ключ включає profile, mode, recency, allow/deny domains, country, languages і query. Зміна будь-якого параметра = cache miss. Один intent різними словами = два API виклики.

---

## Як Великі Фреймворки Реалізують Пошук

### OpenAI Agents SDK + Responses API

OpenAI реалізує пошук як **вбудований серверний tool**. Responses API (наступник Assistants API) має `web_search` як first-class tool type.

Ключові деталі:

- **`search_context_size`** — параметр який контролює, скільки контекстного вікна (128K) виділяється під результати пошуку. Значення: `low`, `medium` (default), `high`.
- **Domain filtering** — allow-list до 100 URL.
- **Non-reasoning моделі** передають query напряму в search backend. **Reasoning моделі** (o-series) можуть планувати multi-step search internally.
- Біллінг: per-search зверху на token costs.

Що важливо для нас: OpenAI дає мало контролю над проміжними кроками. Модель сама вирішує query, фільтрацію, кількість запитів. Це зручно для простих випадків, але не підходить коли потрібен explicit pipeline.

### Anthropic Claude Web Search Tool

Anthropic побудував web search як **серверний tool** на основі Brave Search backend. Дві версії:

- **`web_search_20250305`** (basic): Claude вирішує коли шукати, виконує пошук, повертає відповідь з citations.
- **`web_search_20260209`** (dynamic filtering): Claude може писати і виконувати Python-код для post-processing/фільтрації сирого HTML **до того як він потрапить у контекстне вікно**. Це значно зменшує кількість нерелевантних токенів.

Параметри контролю:

- **`max_uses`** — обмеження кількості пошуків за один запит (наприклад, 5).
- **`allowed_domains` / `blocked_domains`** — domain filtering.
- **`user_location`** — для локалізованих результатів.
- Ціна: **$10 за 1,000 пошуків** + стандартні token costs.
- Citations автоматично включаються в кожну відповідь.
- `encrypted_content` потрібно передавати назад у multi-turn розмовах.

Що важливо для нас: dynamic filtering версія — цікава ідея (LLM пише Python для фільтрації сирого HTML), але це все ще model-managed пошук. Для нашого explicit pipeline нам потрібно більше контролю над кожним кроком.

### LangChain / LangGraph

LangGraph використовує **graph-based execution model** з шістьма production-ready features: parallelization, streaming, checkpointing, human-in-the-loop, tracing, task queues.

Пошук реалізується як:

- **Tool nodes** в state graph — отримують input як channel data, публікують результати назад.
- **ReAct pattern** (Reason → Act → Observe) — дефолтний loop для search agents.
- **Supervisor pattern** — manager agent розподіляє sub-queries між спеціалізованими search workers.
- **Scatter-gather** — розкидає queries на кілька search провайдерів паралельно, консолідує результати.
- **Checkpointing** — дозволяє відновлення з проміжних станів якщо пошуковий крок впав, замість рестарту з нуля.

Що важливо для нас: scatter-gather паттерн (паралельні sub-queries до різних провайдерів + консолідація) — це саме те, чого нам бракує. Наш sequential fallback chain — це антитеза scatter-gather.

### CrewAI

- Вбудовані tools через `crewai-tools`: `SerperDevTool`, `WebsiteSearchTool`, custom tools через `BaseTool`.
- Role-based agent design: "Researcher" agent використовує search tools, "Writer" agent використовує результати.
- Додав **Flows** (state-machine layer) у 2025 поряд із classic Process model.
- **Swarm patterns** з кінця 2025 для agent-initiated handoffs.

Що важливо для нас: розділення ролей (researcher vs writer) — це те ж саме, що наше розділення search pipeline vs final synthesis. CrewAI підтверджує, що це правильний паттерн.

### AutoGen (v0.4+)

- Перейшов на **async-first, event-driven архітектуру** (AgentChat API) у 2025.
- Tools реєструються з agents і викликаються в рамках conversation turns.
- `SelectorGroupChat` — динамічний вибір який agent говорить наступним на основі контексту розмови.
- Підтримує max iterations cap для запобігання runaway loops.

### Azure AI Search: Agentic Retrieval

Azure AI Search дає найчіткішу reference architecture для query decomposition:

1. **LLM аналізує** повний chat thread + query щоб визначити information needs.
2. **Декомпозує** складні питання в focused sub-queries (наприклад, "знайди готель біля пляжу з трансфером і вегетаріанськими ресторанами" → 3 sub-queries).
3. **Запускає sub-queries паралельно** — кожен проходить semantic reranking.
4. **Мерджить результати** в unified response з: grounding data, source references, execution plan.
5. Використовує **fast models (gpt-4o-mini)** для query planning щоб мінімізувати latency.

Ключова метрика: в середньому **3 sub-queries на query plan**, кожен з reranking до 50 чанків.

---

## Провайдери Пошуку: Порівняння З Числами

### Зведена Таблиця Бенчмарків

За даними AIMultiple (бенчмарк 8 API, 2026):

| Провайдер | Agent Score | Latency | Ціна за 1K queries | Найкраще для |
|-----------|-------------|---------|---------------------|--------------|
| **Brave Search** | 14.89 (1-ше) | 669ms | $5–9 | Баланс швидкості і якості |
| **Firecrawl** | 14.58 (2-ге) | ~2s | ~$0.83 | Інтегрований search + extraction |
| **Exa** | 14.39 (3-тє) | Sub-second | $1.50 | Semantic/conceptual research |
| **Tavily** | 13.67 (5-те) | 400–1200ms | $8 | RAG системи, citations |
| **Perplexity** | 12.96 (7-ме) | 11s+ | $5 | Pre-synthesized відповіді |
| **SerpAPI** | 12.28 (8-ме) | Varies | $15+ | Multi-engine enterprise |
| **Serper** | N/A | Fast | $0.30–1.00 | Дешевий Google SERP доступ |

### Brave Search API

**Score: 14.89 (найвищий). Latency: 669ms. Ціна: $5–9 за 1K queries.**

- Власний незалежний індекс (30B+ сторінок), не залежить від Google/Bing.
- Найнижча latency серед усіх провайдерів у бенчмарках.
- Flat per-request pricing (передбачувані витрати).
- Privacy-friendly для regulated індустрій (healthcare, legal, finance).
- Фільтри: `freshness`, `language`, `country`, extra snippets.

Обмеження:

- Не дає content extraction — потрібен окремий scraping step.
- Немає semantic/deep search capabilities як у Exa.
- Простий keyword-based пошук, не "розуміє" intent.

Роль для Smartest: **найкращий all-rounder і primary fallback**. Раніше ми ставили Brave як "cheap fallback", але бенчмарки 2026 показують, що він об'єктивно найкращий за якістю серед усіх API. Варто переглянути його роль з fallback на co-primary.

### Firecrawl

**Score: 14.58 (2-ге). Latency: ~2s. Ціна: ~$0.83 за 1K queries.**

- Інтегрований search + extraction в одному API.
- Чудово підходить для pipeline де потрібно одночасно знайти і витягнути контент.
- Дуже дешевий.
- Відносно новий, менше документації та integration examples.

Обмеження:

- Повільніший за Brave.
- Менш відомий, менше production references.

Роль для Smartest: **потенційний кандидат для заміни зв'язки "search + окремий extract"**. Раніше не розглядався. Варто протестувати як альтернативу Tavily для extraction.

### Exa

**Score: 14.39 (3-тє). Latency: Sub-second. Ціна: $1.50 за 1K базових queries.**

- Neural embeddings — знаходить концептуально пов'язаний контент, який keyword search пропускає.
- Повертає структуровані дані про сторінки (не просто URL + snippet).
- Типи пошуку: `auto`, `deep`, `deep-reasoning`, `instant`, `neural`, `fast`.
- Категорії: `news`, `research paper`, `financial report`, `company`, `people` тощо.
- Фільтри: `includeDomains`/`excludeDomains`, `startPublishedDate`/`endPublishedDate`, `startCrawlDate`/`endCrawlDate`, `includeText`/`excludeText`.
- Content fields: `text`, `highlights`, `summary`.
- **`additionalQueries`** для deep search — можна передати кілька query formulations.

Обмеження:

- Variable credit pricing (75–750+ за search) — складно передбачити витрати.
- Deep search дорожчий і повільніший.

Роль для Smartest: **primary для docs/research/technical profiles**. Це підтверджується і попереднім рішенням. Exa єдиний провайдер який реально "розуміє" semantic intent для research queries.

### Tavily

**Score: 13.67 (5-те). Latency: 400–1200ms. Ціна: $8 за 1K queries.**

- Позиціонується спеціально для AI agents і RAG систем.
- Окремі endpoints: `/search`, `/extract`, `/crawl`, `/map`, `/research`.
- Параметри: `topic` (`general`, `news`, `finance`), `search_depth` (`basic`, `advanced`), `time_range`/`start_date`/`end_date`, `include_domains`/`exclude_domains`, `include_raw_content`.
- **`chunks_per_source`** — повертає тільки релевантні до query фрагменти замість full page. Це middle ground між snippet і full extraction.
- Дає **per-result relevance score** (0–1). Рекомендація: фільтрувати `score > 0.7`.
- `search_depth: "advanced"` коштує 2 кредити замість 1.

Best practices від Tavily:

- Default `max_results: 5` — підвищення ризикує lower-quality returns.
- Тримати queries під 400 символів.
- Використовувати chunks для targeted info; content summaries для загального контексту.
- `include_raw_content: true` тільки після initial search ідентифікував relevant URLs (**"map then extract" pattern**).

Обмеження:

- Agent score нижчий за Brave, Firecrawl, Exa.
- Advanced search дорожчий (2x credits).

Роль для Smartest: **primary extraction/crawl layer + secondary search**. Tavily найсильніший не як єдиний "пошук на все", а як **extraction companion**: `/extract` для витягування чистого контенту з URL, `/crawl` для site-focused завдань, `chunks_per_source` для точного context window management.

### Perplexity Search API / Sonar

**Score: 12.96 (7-ме). Latency: 11s+. Ціна: $5 за 1K queries.**

Perplexity має кілька продуктів:

- **Search API** — raw ranked results, multi-query, domain/country/language filters, `max_tokens_per_page` і `max_tokens` для content budget.
- **Sonar** (base) — fast, lightweight Q&A з grounded відповідями.
- **Sonar Pro** — multi-step reasoning, 2x citations, більше context window.
- **Sonar Pro Search** — автономні multi-step research workflows.

OpenAI-сумісний Chat Completions формат (drop-in replacement).

Обмеження:

- **Найвища latency серед усіх провайдерів (11s+).** Це критично для UX.
- Agent score нижчий за конкурентів (7-ме місце з 8).
- Pre-synthesized відповіді дають менше контролю.

Роль для Smartest: **переоцінка потрібна.** У попередньому рішенні Perplexity Search API був primary для general/news. Але бенчмарки 2026 показують:

1. Brave кращий за якістю (14.89 vs 12.96).
2. Brave в 16x швидший (669ms vs 11s+).
3. Perplexity дорожчий за Brave при нижчій якості.

Perplexity Sonar корисний як **"research oracle"** для складних питань де потрібна готова синтезована відповідь з citations — але не як primary raw search provider. Search API корисний для multi-query в одному виклику, але latency може бути dealbreaker.

### Serper

**Latency: Fast. Ціна: $0.30–1.00 за 1K queries.**

- Найдешевший доступ до Google SERP.
- Простий API, швидкий response.
- Не дає content extraction — тільки SERP results.

Роль для Smartest: **cheap fallback для Google-like results**, або для випадків де потрібен саме Google ranking.

### SerpAPI

**Ціна: $15+ за 1K queries. 99.9% uptime SLA.**

- 40+ search engines.
- Enterprise-grade reliability.
- 10–50x дорожчий за Serper при схожому функціоналі.

Роль для Smartest: **не потрібен.** Serper дає достатньо Google SERP за набагато меншу ціну.

### Вбудовані Пошукові Інструменти Моделей

#### OpenAI `web_search`

- Domain filtering (allow-list до 100 URLs).
- `search_context_size`: low/medium/high.
- Sources автоматично включені.
- Модель сама контролює query і кількість пошуків.

#### Anthropic `web_search`

- Brave Search backend.
- `max_uses`, `allowed_domains`/`blocked_domains`, `user_location`.
- $10 за 1K пошуків + token costs.
- Dynamic filtering версія дозволяє Python-based post-processing.

#### Gemini `google_search`

- Повертає `groundingMetadata` з query, chunks, citation mapping.
- Integrated з Google Search index.
- Контроль через `dynamic_threshold`.

Спільна проблема всіх трьох: це **model-managed search**. Модель сама вирішує коли шукати, які query будувати, як синтезувати. Це зручно для fast start, але не підходить для explicit pipeline де planner, query composer, evaluator і synthesis — окремі шари.

Роль для Smartest: **не primary retrieval, а fallback / verification / fast grounded mode** для окремих сценаріїв.

---

## Архітектурні Паттерни Для Агентного Пошуку

### Паттерн 1: Query Decomposition (Найбільший Impact)

**Проблема:** складне питання → один пошуковий запит → посередні результати.

**Рішення:** LLM (cheap, fast model) аналізує питання і розбиває на 1–3 focused sub-queries, кожен з яких шукається окремо.

**Evidence:** Azure AI Search показує в середньому 3 sub-queries на query plan, кожен з reranking до 50 чанків. Це reference implementation від Microsoft для agentic retrieval.

**Як реалізувати:**

```
Input:  "Як нові санкції ЄС вплинуть на ціни газу в Європі?"
         ↓
Query Planner (gpt-4o-mini, дешево і швидко):
  sub_query_1: "EU new sanctions Russia 2026"
  sub_query_2: "European gas prices forecast sanctions impact"
  sub_query_3: (optional) "EU energy policy sanctions alternatives"
         ↓
Parallel search: кожен sub-query до свого провайдера
         ↓
Merge + dedup + rank
         ↓
Synthesize
```

**Критичний detail:** для planning використовувати дешеву модель (gpt-4o-mini, ~40-60% cost reduction порівняно з main model). Дорогу модель — тільки для фінального синтезу.

### Паттерн 2: Scatter-Gather (Паралельний Multi-Provider)

**Проблема:** sequential fallback chain — перший провайдер що дав ≥2 результати виграє.

**Рішення:** розкидати sub-queries на кілька провайдерів паралельно, потім консолідувати найкращі результати.

**Як реалізувати:**

```
sub_query_1 (factual)  → Brave  (fast, high quality)
sub_query_2 (research) → Exa    (semantic, deep)
sub_query_3 (news)     → Tavily (topic=news, recent)
         ↓  (asyncio.gather)
All results merged → normalized → ranked → top-N to synthesis
```

**Переваги:**

- Кожен провайдер отримує запит під який він найкраще підходить.
- Загальна latency = max(individual latencies) замість sum.
- Якщо один провайдер впав — є результати від інших.

### Паттерн 3: Map Then Extract

**Проблема:** витягувати full page content для кожного URL — повільно, дорого, часто марно.

**Рішення:** двохфазний підхід.

**Фаза 1 (Map):** пошук зі snippets only. Оцінити чи достатньо.

**Фаза 2 (Extract):** якщо snippets недостатньо → витягнути full content **тільки для top 1-2 URLs** з найвищим relevance score.

**Evidence:** Tavily best practices рекомендують `include_raw_content: true` тільки після initial search ідентифікував relevant URLs. Tavily `chunks_per_source` — middle ground що повертає тільки релевантні фрагменти.

**Конкретні правила для Smartest:**

- Якщо snippets already sufficient → extraction не запускається.
- Якщо evaluator каже "джерела поверхневі" → extract top 2-3 URL.
- Якщо задача source-first ("знайди першоджерело", "що там у документації") → extract/crawl одразу.
- Використовувати Tavily `chunks_per_source` замість raw page fetch де можливо.

### Паттерн 4: Retry Зі Зміною Стратегії

**Проблема:** retry = новий query, ті самі провайдери. Якщо провайдер не підходить для цього типу запиту — скільки не retry, результати будуть погані.

**Рішення:** кожна ітерація змінює не тільки query, а й стратегію.

| Attempt | Що змінюється |
|---------|---------------|
| 1 | Primary query → primary provider для цього profile |
| 2 | Reformulated query → **інший провайдер** (наприклад, з Brave на Exa) |
| 3 | Broader/narrower query → **інший тип пошуку** (semantic замість keyword) або extract/crawl |

**Evidence:** research на 14M+ real search requests (arxiv) показує що agents віддають перевагу **local refinement і facet pivots** over deliberate broadening or backtracking.

Max 2-3 retry. Кожен retry — з конкретною причиною ("не знайшли дати" → шукаємо з recency фільтром; "результати нерелевантні" → перемикаємо на semantic search).

### Паттерн 5: Evidence Normalization Layer

**Проблема:** різні провайдери повертають різні поля, різну структуру, різне scoring.

**Рішення:** єдиний `NormalizedResult` між провайдером і evaluation/synthesis.

```
NormalizedResult:
  url: str
  title: str
  snippet: str           # уніфіковано з content/summary/highlights
  relevance_score: float  # 0-1, від провайдера або обчислений
  source_provider: str
  published_date: str | None
  domain: str             # витягнутий з URL
```

**Чому це важливо:** evaluation і synthesis повинні працювати з одноманітними даними. Зараз evaluator бачить різні поля від різних провайдерів — це робить scoring нестабільним.

Tavily вже дає per-result `score` (0-1). Для інших провайдерів потрібно обчислювати на основі: query term overlap, snippet length, preferred domain match, low-signal markers.

### Паттерн 6: Observation Masking

**Проблема:** кожен крок пошуку додає результати в context window. Після 3 ітерацій window переповнений.

**Рішення:** після кожного кроку замінювати старі tool outputs placeholder'ами, залишаючи тільки reasoning history.

**Evidence:** дослідження JetBrains Research показує що observation masking outperforms LLM summarization — **50%+ cost reduction** при рівній або кращій performance. Agents зберігають reasoning trace але "забувають" старі raw results.

**Як застосувати в Smartest:**

- Після кожної пошукової ітерації: зберегти evaluation reasoning і retry cause, замінити сирі results placeholder'ом.
- Final synthesis бачить тільки: aggregated best results + evaluation summary, не весь history tool calls.

### Паттерн 7: Lost-in-the-Middle Ordering

**Проблема:** LLM найкраще запам'ятовують початок і кінець контексту, середина "губиться".

**Рішення:** найрелевантніші результати ставити **першими і останніми**, менш релевантні — в середину.

**Evidence:** це добре документований ефект (Liu et al., "Lost in the Middle"), підтверджений на practice.

### RAG vs Live Search vs Grounded Generation

| Підхід | Коли використовувати | Характеристики |
|--------|---------------------|----------------|
| **RAG** | Відомий корпус, приватні дані, policy docs, product docs | Precision grounding, low hallucination, контрольовані витрати |
| **Live Web Search** | Поточні події, дані що змінюються, факти за межами training cutoff | Real-time але вища latency і вартість |
| **Grounded Generation** | Комбінація обох підходів | Найкраща якість але найскладніша реалізація |
| **Pre-synthesized (Perplexity Sonar)** | Складні research питання де потрібна готова відповідь | Найвища latency, найпростіша інтеграція |

Правило: якщо головна проблема — **галюцинації на власному контенті**, починай з RAG. Якщо потрібна **поточна/зовнішня інформація** — live search. Якщо обидва — agentic RAG з search як fallback tool.

---

## Anti-Patterns: Що Точно Не Треба Робити

### 1. Over-Fetching Pages

**Не робити:** `include_raw_content: true` на кожному search.

**Робити:** "map then extract" pattern — пошук зі snippets, потім extract тільки для relevant URLs.

**Чому:** full page extraction = більше latency, більше токенів, більше шуму. Часто snippets достатньо для відповіді.

### 2. Single Monolithic Query

**Не робити:** одне складне питання → один довгий search query.

**Робити:** break compound questions на 1-3 focused sub-queries, запускати паралельно.

**Чому:** один query "розкажи про нові санкції ЄС і як це вплине на газ" дає гірші результати ніж два focused queries. Це підтверджено Azure AI Search reference architecture.

### 3. Не Кешувати Результати

**Не робити:** кожен пошук = новий API call.

**Робити:** semantic cache (vector similarity) для усунення ~31% redundant queries. Prompt caching (Anthropic: 90% savings на cached input; OpenAI: ~50%) — найвищий ROI optimization.

**Чому:** research показує ~31% cache hit rate на semantic caching для search queries.

### 4. Дозволяти LLM Контролювати Все

**Не робити:** покладатися що модель сама обмежить кількість пошуків, стратегію, budget.

**Робити:** structured controls — `max_uses`, iteration caps, token budgets, explicit provider routing.

**Чому:** без structured controls ReAct loops можуть працювати 10+ циклів і споживати 50x більше токенів ніж linear passes.

### 5. Unconstrained Multi-Turn Loops

**Не робити:** ReAct loop без hard cap на ітерації.

**Робити:** max 2-3 ітерації з явною зміною стратегії на кожній.

**Чому:** кожна додаткова ітерація платить output token premium (3-8x дорожче за input tokens). ReAct без ліміту може з'їсти весь budget на одному запиті.

### 6. Verbose Intermediate Reasoning

**Не робити:** кожен проміжний крок (planner, query composer, evaluator) генерує розгорнутий chain-of-thought.

**Робити:** suppress CoT для проміжних кроків. Structured JSON output замість free-text reasoning.

**Чому:** output tokens 3-8x дорожчі за input. Reasoning корисний тільки для final synthesis, не для кожного проміжного кроку.

### 7. Quadratic Context Growth

**Не робити:** dump повну conversation history між agents / між ітераціями.

**Робити:** observation masking — замінити старі tool outputs placeholder'ами.

**Чому:** outperforms LLM summarization і в cost, і в reliability (JetBrains Research).

### 8. Ігнорувати Lost-in-the-Middle Ефект

**Не робити:** сортувати результати хронологічно або по провайдеру.

**Робити:** найкращі результати — першими і останніми в промпті. Менш релевантні — в середину.

**Чому:** LLM зважують початок і кінець промптів значно більше ніж середину. Важлива інформація в середині може бути "згублена".

### 9. Кеш Що Занадто Гранулярний

**Не робити:** cache key = `profile|mode|recency|allow|deny|country|languages|query` — будь-яка зміна параметра = miss.

**Робити:** нормалізувати query перед хешуванням (lowercase, trim, sort words). Або semantic cache на embedding similarity.

**Чому:** "новини про Apple" і "latest Apple news" — один intent, але різні cache keys. Це витрачає API quota на redundant calls.

### 10. Silent Provider Failures

**Не робити:** provider fail → log warning → try next.

**Робити:** розрізняти "provider not available" (skip permanently), "timeout" (might retry once), "rate limited" (backoff). Логувати конкретну помилку, не generic warning.

**Чому:** без цього розрізнення неможливо діагностувати проблеми і неможливо зробити adaptive provider selection.

---

## Практичні Деталі Імплементації

### Скільки Результатів Витягувати

- **Tavily default 5 — хороша стартова точка.** Підвищення ризикує lower-quality returns.
- Для broad research: 5-10 результатів з post-filtering по relevance score.
- Для focused factual питань: 3-5 результатів достатньо.
- Azure agentic retrieval: reranks до 50 чанків per sub-query, повертає тільки top matches.

### Коли Витягувати Full Page Content vs Snippets

- **Починати зі snippets** (default behavior більшості API) — вони оптимізовані для LLM consumption.
- **Extract full content тільки коли:**
  - Snippet явно недостатній (технічна документація, code examples).
  - Ідентифіковано конкретний high-relevance URL після initial search.
  - Потрібна structured data extraction (таблиці, специфікації).
- **Tavily `chunks_per_source`** — middle ground: повертає query-relevant chunks замість full pages. Це оптимальний варіант для більшості випадків.

### Token Budget Management

- Agents роблять **3-10x більше LLM calls** ніж simple chatbots. Один user request може спожити 5x token budget прямого completion.
- **Hard limits обов'язкові:** max iterations cap, per-trace token ceiling, user/workflow rate limiting.
- **Тримати context window < 80%** від token limit для reliability.
- **Model routing cascades:** cheap models (gpt-4o-mini) для query planning і evaluation, expensive models тільки для final synthesis — **40-60% cost reduction**.
- **Prompt compression** (LLMLingua): до 20x compression зі збереженням semantic meaning.
- Output tokens коштують **3-8x більше** ніж input tokens — стиснути outputs до structured data only.

### Як Форматувати Результати Для LLM

- **Observation masking** (замінити старі tool outputs placeholder'ами зберігаючи reasoning history) outperforms LLM summarization — 50%+ cost reduction.
- Тримати **rolling window ~10 recent turns** для agent context.
- Структурувати результати як: `[Source Title](URL) — relevance: X.XX\n<snippet text>`.
- **Найрелевантніші першими і останніми** (primacy + recency bias), менш релевантні в середину.
- Видалити boilerplate, navigation text, реклами з extracted content перед передачею в LLM.

### Semantic Caching

Два типи кешування:

1. **Prompt caching** — для repeated prefixes (system prompts, instructions). Anthropic: 90% savings. OpenAI: ~50%.
2. **Semantic caching** — для search queries. Vector similarity замість exact match. ~31% hit rate за дослідженнями.

Мінімальний крок для Smartest: нормалізувати query перед хешуванням (lowercase, strip punctuation, sort words). Це дасть більше cache hits без потреби в vector DB.

### Timeouts і Circuit Breakers

Поточні timeouts у Smartest: 15s (bing, serper), 20s (brave, exa, openai), 25s (perplexity, tavily) — inconsistent і без rationale.

Рекомендації:

- **Fast providers (Brave, Serper, Exa):** 5-8s timeout. Якщо не відповіли за цей час — щось не так.
- **Medium providers (Tavily search):** 10-15s timeout.
- **Slow providers (Perplexity, Tavily extract):** 15-20s timeout.
- **Circuit breaker:** якщо провайдер впав 3 рази поспіль — вимкнути на 5 хвилин, спробувати знову.
- **Adaptive timeout:** track p95 latency per provider, set timeout = p95 * 1.5.

---

## Рекомендована Архітектура Для Smartest

### Цільовий Pipeline: 6 Фаз

```
User Query
    ↓
┌─────────────────────────────────────────────────────────────┐
│  ФАЗА 1: QUERY PLANNER                                     │
│  Model: gpt-4o-mini (дешево, швидко)                        │
│  Input: user query + 6-msg dialogue excerpt                 │
│  Output:                                                    │
│    - sub_queries: list[str]     (1-3 focused queries)       │
│    - query_type: str            (fact/news/research/compare) │
│    - profiles: list[str]        (per sub-query profile)     │
│    - need_extract: bool                                     │
│    - recency_days: int | None                               │
│    - alternative_formulations: list[str]                    │
│  Max output: structured JSON, no CoT                        │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  ФАЗА 2: PARALLEL SEARCH                                   │
│  asyncio.gather() по sub-queries                            │
│  Провайдер обирається per sub-query за profile:             │
│    fact/general → Brave (669ms, score 14.89)                │
│    news        → Brave + Tavily(topic=news)                 │
│    research    → Exa (semantic, deep)                       │
│    docs        → Exa (category filter)                      │
│  5 результатів per sub-query                                │
│  Fallback order: Brave → Tavily → Serper → DDG              │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  ФАЗА 3: NORMALIZE & RANK                                  │
│  Кожен результат → NormalizedResult                         │
│  Dedup по domain + title similarity                         │
│  Relevance scoring:                                         │
│    - Tavily score (якщо є) → використати як є               │
│    - Інші → query term overlap + snippet quality + domain   │
│  Відсічка: score < 0.5 → drop                              │
│  Sort: relevance descending                                 │
│  Lost-in-the-middle reorder для final prompt                │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  ФАЗА 4: SELECTIVE EXTRACT (conditional)                    │
│  Якщо snippets sufficient → skip                            │
│  Якщо потрібно більше контексту:                            │
│    - Top 2-3 URLs → Tavily chunks (preferred)               │
│    - Fallback: Tavily extract → fetch_page                  │
│  Якщо source-first задача: extract одразу                   │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  ФАЗА 5: EVALUATE                                          │
│  Per sub-query: чи є відповідь?                             │
│  Якщо gap знайдено:                                         │
│    - targeted retry тільки для конкретного gap              │
│    - зміна стратегії (інший провайдер, інший query type)    │
│    - max 2 retries total                                    │
│  Якщо все ще insufficient після retries:                    │
│    - повернути чесну невдачу з partial evidence             │
│    - НЕ "дотискати" synthesis з слабких snippets            │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  ФАЗА 6: SYNTHESIZE                                        │
│  Model: capable model (gpt-4o, claude-sonnet тощо)          │
│  Input:                                                     │
│    - Ranked NormalizedResults (best first & last)           │
│    - User intent                                            │
│    - Style policy                                           │
│  Output:                                                    │
│    - Human-readable відповідь                               │
│    - Inline citations                                       │
│  НЕ бачить: planner trace, query composer reasoning,        │
│             tool chatter, provider routing details           │
└─────────────────────────────────────────────────────────────┘
```

### Оновлена Provider Matrix

На основі бенчмарків 2026 і практичного аналізу:

| Profile | Primary | Co-primary / Extract | Fallback |
|---------|---------|---------------------|----------|
| `general` | Brave | — | Tavily, Serper |
| `news` | Brave | Tavily (topic=news) | Serper |
| `docs` | Exa (category) | Tavily extract/crawl | Brave |
| `research_paper` | Exa (category=research paper) | — | Brave |
| `site_search` | Tavily search/crawl | — | fetch_page |

**Зміна відносно попереднього рішення:** Brave піднято з fallback до primary на основі бенчмарків (score 14.89, latency 669ms, $5-9/1K). Perplexity знижено — latency 11s+ неприйнятна для primary provider, score 12.96 нижчий за альтернативи. Perplexity залишається як optional research oracle для складних питань де потрібна готова синтезована відповідь.

**Новий кандидат:** Firecrawl (score 14.58, $0.83/1K) варто протестувати як альтернативу Tavily для integrated search + extraction. Дуже дешевий при високій якості.

### Конкретні Зміни В Коді Smartest

#### 1. Query Planner (новий модуль)

Замінити поточний `build_search_task()` на query planner що:

- Приймає user query + dialogue excerpt.
- Повертає structured plan: sub-queries, profiles, alternative formulations.
- Використовує cheap model (gpt-4o-mini).
- Нарешті заповнює `alternative_queries` в SearchTask.

#### 2. NormalizedResult (нова структура)

Додати між провайдерами і evaluation/synthesis. Кожен провайдер конвертує свій output в єдину схему. Все що далі бачить тільки NormalizedResult.

#### 3. Parallel Search Execution

Замінити sequential fallback chain на `asyncio.gather()`. Різні sub-queries → різні провайдери → паралельно.

#### 4. Smart Evaluation

Замінити "3 results + 2 domains = ok" на:

- Per sub-query перевірка чи є відповідь.
- Relevance scores від провайдерів.
- Targeted retry тільки для конкретного gap.
- Зміна стратегії (provider + query type) при retry.

#### 5. Selective Extract

"Map then extract": snippet-first, full content тільки для top URLs коли snippet недостатній. Tavily chunks як default extraction method.

#### 6. Synthesis Isolation

Final responder бачить тільки: ranked NormalizedResults + user intent + style policy. Не бачить planner trace, query composer reasoning, tool chatter.

---

## Джерела

### Офіційна Документація Провайдерів

- OpenAI Web Search: https://platform.openai.com/docs/guides/tools-web-search
- OpenAI Agents SDK Tools: https://openai.github.io/openai-agents-python/tools/
- OpenAI New Tools for Building Agents: https://openai.com/index/new-tools-for-building-agents/
- Anthropic Web Search Tool: https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool
- Anthropic Advanced Tool Use: https://www.anthropic.com/engineering/advanced-tool-use
- Anthropic Web Search API announcement: https://www.anthropic.com/news/web-search-api
- Tavily Best Practices: https://docs.tavily.com/documentation/best-practices/best-practices-search
- Tavily Agent Skills: https://docs.tavily.com/documentation/agent-skills
- Tavily 101: https://www.tavily.com/blog/tavily-101-ai-powered-search-for-developers
- Tavily Search endpoint: https://docs.tavily.com/documentation/api-reference/endpoint/search
- Tavily Extract endpoint: https://docs.tavily.com/documentation/api-reference/endpoint/extract
- Tavily Crawl endpoint: https://docs.tavily.com/documentation/api-reference/endpoint/crawl
- Perplexity Sonar API: https://docs.perplexity.ai/docs/sonar/quickstart
- Perplexity Search API: https://docs.perplexity.ai/docs/search/quickstart
- Perplexity Agent API: https://docs.perplexity.ai/docs/agent-api/quickstart
- Perplexity Sonar Pro announcement: https://www.perplexity.ai/hub/blog/introducing-the-sonar-pro-api
- Exa Search API: https://docs.exa.ai/reference/search
- Exa Docs: https://exa.ai/docs/reference/search
- Brave Search API: https://brave.com/search/api/
- Brave Search API docs: https://api-dashboard.search.brave.com/app/documentation/web-search/get-started
- Gemini Google Search Grounding: https://ai.google.dev/gemini-api/docs/google-search
- Serper: https://serper.dev/

### Бенчмарки і Порівняння

- AIMultiple 2026 Agentic Search Benchmark (8 APIs): https://aimultiple.com/agentic-search
- Firecrawl Top Web Search APIs 2026: https://www.firecrawl.dev/blog/top_web_search_api_2025
- WebSearchAPI Guide Beyond Tavily: https://websearchapi.ai/blog/tavily-alternatives
- Exa vs Tavily vs Serper vs Brave AN Score Comparison: https://dev.to/supertrained/exa-vs-tavily-vs-serper-vs-brave-search-for-ai-agents-an-score-comparison-2l1g

### Architecture References

- Azure AI Search Agentic Retrieval: https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview
- LangGraph Building an Agent Runtime: https://blog.langchain.com/building-langgraph/
- LangGraph Multi-Agent Orchestration 2025: https://latenode.com/blog/ai-frameworks-technical-infrastructure/langgraph-multi-agent-orchestration/langgraph-multi-agent-orchestration-complete-framework-guide-architecture-analysis-2025
- Agent Orchestration 2026 (LangGraph, CrewAI, AutoGen): https://iterathon.tech/blog/ai-agent-orchestration-frameworks-2026

### Research Papers і Аналітика

- JetBrains Research: Efficient Context Management for LLM Agents: https://blog.jetbrains.com/research/2025/12/efficient-context-management/
- AI Agent Cost Optimization (Token Economics, FinOps): https://zylos.ai/research/2026-02-19-ai-agent-cost-optimization-token-economics
- Semantic Caching Measurements: https://www.catchpoint.com/blog/semantic-caching-what-we-measured-why-it-matters
- Prompt Caching vs Semantic Caching: https://redis.io/blog/prompt-caching-vs-semantic-caching/
- Agentic Search in the Wild (14M+ queries, arxiv): https://arxiv.org/html/2601.17617v2
- RAG vs Large Context Window Trade-offs: https://redis.io/blog/rag-vs-large-context-window-ai-apps/
