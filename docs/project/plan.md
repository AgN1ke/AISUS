# План

## Для Чого Цей Документ

Живий оперативний план. Якщо нова модель або новий виконавець заходить у проєкт — саме тут вони повинні зрозуміти: що вже зроблено, що зараз у роботі, який наступний крок і чому саме він. Конкретні кроки імплементації (код, файли, тести) — в `implementation-roadmap.md`. Research — в `docs/research/`.

Статуси: `виконано` | `в роботі` | `заплановано` | `відкладено`.

---

## Етап 0. Дослідницька База — `виконано`

Зібрано і актуалізовано (2026-04-04) research по чотирьох напрямках: провайдери з конкретними цінами і бенчмарками, агентні архітектури з production patterns від 6 major frameworks, multimodal стек з WER/latency/pricing по кожному провайдеру, пошуковий стек з бенчмарками 8 search API.

Артефакти:

- `docs/research/provider-landscape.md` — 10 провайдерів, pricing tables, Chatbot Arena rankings
- `docs/research/agentic-architectures.md` — OpenAI SDK, ADK, Claude Agent SDK, LangGraph, MCP/A2A, anti-patterns
- `docs/research/multimodal-media.md` — image/STT/TTS/video/realtime voice з конкретними моделями і цінами
- `docs/research/search-stack.md` — 8 search API бенчмарк, 7 архітектурних паттернів, 10 anti-patterns

Що це дало: ми більше не вибираємо провайдерів "на відчуття". Є конкретні числа: Brave score 14.89 за 669ms, ElevenLabs Scribe WER 3.1% на українській, GPT-4.1 Nano $0.05/1M для planner'а, Gemini 81% MMMU-Pro для vision. Ці числа тепер інформують кожне архітектурне рішення.

## Етап 1. Аудит — `виконано`

Зафіксовано split-brain між legacy (`main.py` + `src/*`) і новим runtime (`run.py` + `adapters/*` + `app/*` + `agent/*`). Вибрано `run.py` як канонічний. Legacy — compatibility tail, не фундамент.

Артефакт: `docs/project/audit-baseline-2026-04-03.md`.

## Етап 2. Стабілізація Runtime — `виконано`

Стабілізовано `run.py`, виправлено критичні дефекти в agent/media/db шарах, піднято два серверних контури: staging (`/opt/smartest-staging`) і production (`/opt/smartest`). Базовий тестовий контур зелений, live smoke-test пройдений.

Артефакт: `docs/project/server-smartest.md`.

---

## Етап 3. Capability Split + Provider Routing — `в роботі`

Це поточний головний фокус. Мета: перевести бот з "одного великого OpenAI-потоку" в систему де кожна capability (текст, пошук, vision, voice, memory) має свій provider binding, свій контракт і свій fallback.

### Що Вже Є В Runtime

**Capability infrastructure:**
- `core/provider_registry.py` — `ProviderBinding`, capability-level resolution `provider/adapter/model`.
- `core/env.py` — env-контракти `CAPABILITY_<NAME>_PROVIDER/ADAPTER/MODEL`, `PROVIDER_<NAME>_API_KEY/BASE_URL`.
- `agent/llm.py` — binding по capability замість одного global client. Але: global `_client`/`_clients` все ще живуть як implicit singletons.
- Native Gemini adapter (`gemini_generate_content`) для tool-less capabilities — перший не-OpenAI transport.

**Planner/routing:**
- `agent/planner.py` — heuristic short-circuit для media/search + LLM fallback для неоднозначних запитів.
- `app/chat_geometry.py` — `MessageGeometry` з reply target, media kind, mention detection, addressed flag.
- `core/prompts.py` — централізовані промпти (persona, planner, search composer/evaluator/synthesis, vision, memory).
- `app/message_logic.py` — `process_message()` вже розбитий на окремі шари `check_access()`, `build_user_task()`, `plan_execution()`, `execute_plan()`, `send_response()`. Сам `process_message()` тепер лишається оркестратором, а не god function.

**Operations:**
- Admin UI на `smartest.klawa.top` — env editor, service restart.
- Staging + production контури на VPS.

### Що Потрібно Зробити

Чотири незалежних блоки які можна робити паралельно (Фаза 1):

**Блок 1. Розбити `process_message()` по шарах routing contract.**

Зараз `app/message_logic.py` → `process_message()` — god function ~210 рядків. В одному методі: auth, geometry, media routing, memory, planner, response generation, Telegram send. Це блокує будь-яке нормальне розширення.

Що треба: виділити 5 окремих функцій — `check_access()`, `build_user_task()`, `plan_execution()`, `execute_plan()`, `send_response()`. `process_message()` стає оркестратором на ~50 рядків. Кожна функція — typed input/output, тестується ізольовано.

Чому першим: поки message flow — монолітний, кожна нова capability вростає в центр хаотично. Це unlock для всього іншого.

**Блок 2. NormalizedResult для search results.**

Зараз різні search провайдери повертають різні dict'и: Bing — `name/snippet`, Tavily — `title/content/score`, Exa — `summary/highlights`. Evaluator і synthesis бачать різнорідні дані — scoring нестабільний.

Що треба: `NormalizedResult` dataclass (url, title, snippet, relevance_score 0-1, source_provider, domain, published_date). Конвертер per provider. Tavily score використовувати as-is, для решти — computed. Все що після `search_web()` бачить тільки `NormalizedResult`.

Чому зараз: без нормалізації неможливо зробити ані smart evaluation, ані parallel search merge, ані lost-in-the-middle ordering.

**Блок 9. Cache normalization і cost logging.**

Cache key зараз = `profile|mode|recency|allow|deny|country|languages|query` — будь-яка зміна = miss. "Новини Apple" і "новини apple" = два різних keys. `datetime.utcnow()` deprecated з Python 3.12.

Що треба: нормалізувати query перед хешуванням (lowercase, trim, sort words). Спростити key до `v3|{profile}|{normalized_query}`. Замінити `datetime.utcnow()`. Додати structured logging для кожного search API call (provider, query, result count, latency).

**Блок 10. Прибрати global state і dead code.**

Global `_client: Optional[OpenAI] = None` і `_clients: dict = {}` в `agent/llm.py` — implicit singletons. Мертвий код: `src/chat_history_manager.py` (не інтегрований), `commands/admin.py` (стаби), `knowledge/threads.py` (не викликається), `encode_to_base64.py`, `whisper_tool.py` (заглушка). `SEARCH_TRIGGER_PATTERNS` дублюються в `runner.py` і `planner.py`.

Що треба: factory function замість globals, видалити dead code, централізувати дублікати.

### Критерій Закриття Етапу 3

- `process_message()` розбитий по шарах, кожен шар з тестом.
- `NormalizedResult` — єдина валюта між search providers і evaluation/synthesis.
- Немає global `_client` в `agent/llm.py`.
- Dead code видалений, `pytest -q` зелений.

---

## Етап 3a. Search Orchestration — `в роботі`

Пошук — одна з найболючіших user-facing проблем. Зараз він вже не "магія моделі" (є SearchTask, evaluator, retry loop), але архітектурно це все ще "один запит → один провайдер → оцінка → може retry". Треба перевести на повноцінний pipeline з decomposition, parallel execution і smart evaluation.

### Що Вже Є В Runtime

- `SearchTask` з `mode`, `recency_days`, `preferred_domains` — запит несе policy hints, не тільки голий query.
- Query composer з dialogue context — "ну загугли" будує query з попередніх повідомлень.
- Query Planner baseline — `plan_search_queries()` уже вміє будувати 1-3 sub-queries, заповнювати `alternative_queries` і не валить пошук, якщо planner-model недоступна.
- Heuristic compound fallback — очевидні comparison-запити типу `порівняй новини про OpenAI і Anthropic` тепер ріжуться на окремі sub-queries навіть без допомоги LLM planner-а.
- Parallel sub-query execution — `asyncio.gather()` запускає кілька planned sub-queries одночасно, а failure одного не валить решту.
- Per-sub-query coverage evaluation — evaluator перевіряє покриття кожного sub-query, а retry б’є тільки в конкретний gap.
- Evaluator + retry loop (max 3 iterations) — control-plane оцінка окремо від synthesis, без planner/evaluator trace у фінальному prompt.
- Multi-provider auto-selection — короткий profile-based routing: Brave primary для general/news, Exa для docs/research, Tavily для site-search.
- Gemini search як grounded fallback — працює без зовнішніх search API keys.
- Page extraction policy — не для news/general, тільки коли потрібно.
- Search synthesis не генерується якщо evaluator визнав evidence недостатнім.

### Що Потрібно Зробити

Послідовний ланцюг (Фази 2-5), кожен блок залежить від попереднього:

**Блок 3. Query Planner з decomposition — виконано.**

Що зроблено: `build_search_tasks()` тепер працює через `plan_search_queries()` і повертає `list[SearchTask]` замість одного `SearchTask`, коли запит справді складений. Кожен sub-query несе свій profile і може мати `alternative_queries`. Якщо planner-model повертає сміття, падає або недодекомпозує comparison-запит, runtime не відкочується в хаос, а переходить у heuristic compound fallback.

Що перевірено: прості explicit-search запити лишаються однотактними; comparison-запити декомпозуються; fallback-path не блокує пошук; staging `pytest -q` зелений; live smoke-check у `/opt/smartest/app` показав `2` sub-queries для `порівняй новини про OpenAI і Anthropic`.

**Блок 4. Parallel search execution.**

Зараз: провайдери пробуються послідовно як fallback chain — перший хто дав ≥2 результати виграє, навіть якщо результати нерелевантні.

Що треба: `asyncio.gather()` для sub-queries — кожен до свого провайдера по profile. Brave primary для general/news (score 14.89, 669ms). Exa для docs/research (semantic search). Latency = max(individual) замість sum. Failure одного sub-query не блокує інші. Скорочений fallback: primary → один fallback → stop.

**Блок 5. Smart evaluation.**

Зараз: heuristic "3+ results AND 2+ distinct domains = sufficient" — не перевіряє relevance. LLM evaluator бачить top 5 results по 500 chars і top 2 pages по 1200 chars.

Що треба: per-sub-query coverage check (чи є відповідь на КОЖЕН sub-query), relevance-based heuristic (score ≥ 0.5 замість domain counting), targeted retry тільки для конкретного gap (не для всього запиту). LLM evaluator бачить top 8 results + top 3 pages по 2000 chars + список sub-queries для coverage check.

**Блок 6. Selective extract.**

Зараз: якщо `need_extract=True` — витягуються сторінки для всіх top URLs. Сторінки ріжуться на 1200 chars.

Що треба: snippet-first (за замовчуванням extraction НЕ запускається). Evaluator може запросити extract для конкретних URLs. Tavily `chunks_per_source` замість full page. 4000 chars per page замість 1200. `fetch_page` — крайній fallback.

**Блок 7. Synthesis isolation.**

Зараз: synthesis в `_run_direct_search()` бачить planner trace, evaluator decisions, tool chatter. Результати не reordered.

Що треба: final responder бачить тільки ranked `NormalizedResult` + user intent + style policy. Lost-in-the-middle ordering (найрелевантніші першими і останніми). Inline citations `[1]`, `[2]`. Не бачить control-plane trace.

**Блок 8. Retry зі зміною стратегії.**

Зараз: retry = новий query, ті самі провайдери.

Що треба: attempt 2 → reformulated query + інший провайдер. Attempt 3 → semantic search (Exa) якщо keyword search не дав результатів. Track attempted (query, provider) pairs щоб не пробувати одну комбінацію двічі.

**Блок 11. Тестова матриця.**

E2E search test (decomposition → search → merge → evaluate → synthesis). Retry scenario test (first attempt empty → retry з іншим провайдером). LLM failure tests (invalid JSON → fallback, evaluator timeout → heuristic). Live smoke matrix: 8 сценаріїв від простого factual до provider failover.

### Оновлення Провайдерної Стратегії Search

За бенчмарками 2026 (AIMultiple, 8 API) змінено primary search provider:

| | Brave (новий primary) | Perplexity (старий primary) |
|---|---|---|
| Agent Score | **14.89** (#1 з 8) | 12.96 (#7 з 8) |
| Latency | **669ms** | 11,000ms+ |
| Ціна/1K queries | $5-9 | $5 |

Brave в 16x швидший при вищій якості. Perplexity залишається як optional research oracle для складних питань де потрібна готова синтезована відповідь.

Повна provider routing matrix:

| Profile | Primary | Extract | Fallback |
|---------|---------|---------|----------|
| `general` | Brave | — | Tavily, Serper |
| `news` | Brave | Tavily (topic=news) | Serper |
| `docs` | Exa (category filter) | Tavily extract/crawl | Brave |
| `research_paper` | Exa (category=research paper) | — | Brave |
| `site_search` | Tavily search/crawl | — | fetch_page |

Новий кандидат для оцінки: **Firecrawl** (score 14.58, $0.83/1K) — integrated search + extraction, може замінити зв'язку Brave + Tavily.

### Критерій Закриття Етапу 3a

- Складне питання → 2-3 sub-queries → паралельний search → merged NormalizedResults.
- Retry змінює і query, і провайдера.
- Evaluation per-sub-query, не "3 results = ok".
- Synthesis ізольований, з citations, не бачить control-plane trace.
- E2E тести зелені. Live smoke-test: 8 сценаріїв пройшли.

---

## Етап 4. Telegram Event Normalization — `заплановано`

Це фундаментальна продуктова вимога, не технічний nice-to-have. Бот повинен розуміти розмову як людина: бачити паралельні лінії спілкування в групі, розуміти що тег у reply на чиєсь фото означає "подивись на ЦЕ фото", відслідковувати reply-ланцюжки як окремі гілки діалогу, не плутати контексти різних розмов. Зараз бот зсипує все в одну кашу.

Детальний опис поведінкової моделі і 4 рівнів реалізації — `docs/project/telegram-geometry.md`.

### Що Треба Зробити

**`UnifiedMessage` → `TelegramEvent`:**
- Reply chain: не один hop, а ланцюжок 3-5 повідомлень назад по reply-to-message-id.
- `instruction` vs `target` розділення: "поясни мем" (інструкція) + тегнуте фото (target) — два окремі поля.
- `is_instruction_on_target`: explicit boolean — це інструкція на чуже повідомлення, а не самостійне питання.
- Per-user recent context: "це повідомлення від Андрія, ось його останні 3 звернення до бота".

**Media target resolution:**
- Зараз `select_ptb_media_target()` / `select_telethon_media_target()` — базова логіка "current message або reply target".
- Треба: формальний пріоритет — reply-target media > current media > reply-target text. Інструкція завжди з current message.

**Thread awareness (бажаний):**
- Heuristic thread detection: reply chains + time proximity + participant overlap.
- Memory window per-thread замість per-chat.
- Або інтеграція з Telegram Forum Topics (де threads explicit).

Контракт об'єктів описано в `routing-contract.md`.

### Залежності

Потребує закритого Етапу 3 (розбитий `process_message()` по шарах — інакше TelegramEvent нікуди вбудувати).

---

## Етап 5. Multimodal Pipelines — `заплановано`

Довести до системного стану: voice-in/out, image understanding, video understanding і reply-to-media workflows.

### Ключові Рішення З Дослідження

**Image understanding:**
- Primary: Gemini 2.5 Flash ($0.30/1M, 81% MMMU-Pro — найвищий benchmark). Free tier для development.
- Premium: Claude Sonnet 4.6 ($3/1M) для complex analysis (strong OCR на imperfect images).
- Зараз: OpenAI vision. Переключити на Gemini.

**Video understanding:**
- Primary і єдиний: Gemini 2.5 Pro ($1.25/1M, ~$0.005/хв відео). Native video input: до 1 години, 1 FPS sampling.
- OpenAI і Anthropic НЕ мають native video — тільки frame extraction workaround.
- Зараз: FFmpeg frame extraction + Whisper. Переключити на Gemini native.

**STT:**
- Primary: OpenAI gpt-4o-mini-transcribe ($0.18/hr) — найдешевший capable.
- Budget: AssemblyAI Universal-2 ($0.15/hr).
- Best Ukrainian: ElevenLabs Scribe v2 ($0.22/hr, **WER 3.1%** на українській — найкращий у індустрії). Раніше не існував (випущений січень 2026).
- Зараз: `whisper_tool.py` — заглушка. Підключити реальний STT.

**TTS:**
- Primary: OpenAI tts-1 ($15/1M chars).
- Budget: Google Cloud Standard ($4/1M chars).
- Ukrainian: Google Cloud WaveNet ($16/1M) або ElevenLabs ($60/1M).
- Premium: ElevenLabs Flash v2.5 (75ms latency, voice cloning, emotional control).
- **Deepgram НЕ підтримує українську.** Claude **НЕ має audio API** для developers.
- Зараз: тільки в legacy `src/voice_processor.py`. Перенести в canonical runtime.

**Reply-to-media:**
- Архітектура через media target object: tagged message → media type → extracted content → user instruction → synthesis policy.
- Залежить від Етапу 4 (TelegramEvent з instruction vs target).

### Залежності

Потребує Етапу 4 (нормалізація Telegram event з media target resolution і instruction/target split).

---

## Етап 6. Memory Redesign — `відкладено`

Поточна two-tier memory (recent ~10K tokens + long compressed ~30K) працює базово. Redesign включає: адаптацію моделі пам'яті з `D:\GODOT\chibigochi`, per-thread memory замість per-chat, importance-based retrieval, session awareness.

Потребує: стабільних сесій, Telegram context (Етап 4), capability boundaries (Етап 3).

---

## Етап 7. Control Plane — `в роботі` (мінімальний baseline)

### Що Вже Є

- Password-protected admin UI на `smartest.klawa.top`.
- Env editor (читає і зберігає `.env`).
- Service restart (checkbox → `systemctl restart smartest-bot`).
- `smartest-admin.service` як окремий systemd unit.
- Caddy proxy на `127.0.0.1:8787`.

### Що Потрібно (після стабілізації Етапу 3)

- Edit capability routing через UI, не тільки `.env`.
- Валідація capability bindings (перевірка що API key існує, що model name валідний).
- Model A/B testing UI (переключити capability на інший provider, порівняти якість).
- Cost dashboard (скільки API calls per capability, скільки коштує).

Повноцінний control plane має сенс тільки після того як capability bindings стабільні. Інакше це красива оболонка над тимчасовою архітектурою.

---

## Поточний Робочий Спринт

### Фаза 1 — Паралельна (Етап 3)

Чотири незалежних блоки, можна робити одночасно:

| Блок | Що | Файли | Критерій |
|------|-----|-------|---------|
| 1 | Розбити `process_message()` | `app/message_logic.py` | <50 рядків, кожен шар з тестом |
| 2 | NormalizedResult | `agent/search_task.py`, `agent/tools/web_search.py` | Все після `search_web()` бачить тільки NormalizedResult |
| 9 | Cache + datetime | `agent/tools/web_search.py`, `db/search_repository.py` | "Новини Apple" = "новини apple" в кеші |
| 10 | Dead code + globals | `agent/llm.py`, 5+ файлів видалити | Немає `_client = None` |

Поточний стан Фази 1:

- **Блок 1 — виконано локально.** `process_message()` переведений у шарову оркестрацію; додані окремі unit-тести на access gate, task builder, planner wrapper, executor routing і response sender.
- **Блок 2 — виконано локально.** У search runtime введено `NormalizedResult` і `EvidencePack`; `search_web()` повертає нормалізовані результати, evaluator і synthesis більше не працюють із сирими provider dict'ами, extraction підв'язаний до тих самих result objects.
- **Блок 9 — виконано локально.** Search cache key спрощено до нормалізованого `v3|profile|query`; `datetime.utcnow()` прибрано з search/page cache helpers; додано structured provider-call logging з `provider`, `query`, `results`, `latency_ms`.
- **Блок 10 — виконано локально.** `agent/llm.py` переведено з global `_client/_clients` на явний cached factory `get_llm_client()`; search intent централізовано в окремому модулі; видалено runtime-unreachable legacy-файли й тести, які трималися лише на них.

**Фаза 1 перевірена на staging.** Після синхронізації в `/opt/smartest-staging` повний `pytest` пройшов зелено: `73 passed, 5 warnings`. Це закриває не лише локальну розробку, а й verification-контур Фази 1.

**Наступний крок:** перейти до Фази 4 / Блоків 6+7 (`Selective Extract + Synthesis Isolation`).

### Фаза 2 — Query Planner (Етап 3a) — `виконано`

Блок 3 закритий: decomposition на 1-3 sub-queries працює, `alternative_queries` заповнюються, planner failure має heuristic fallback, staging повний `pytest` зелений, live smoke-check пройдено.

### Фаза 3 — Parallel Search + Evaluation (Етап 3a) — `виконано`

Блоки 4+5 закриті: sub-queries тепер запускаються паралельно через `asyncio.gather()`, provider routing скорочений до profile-aware primary/fallback схеми, evaluator бачить coverage per sub-query і робить targeted retry тільки для конкретного gap. Локальний розширений пакет зелений, staging повний `pytest` зелений.

### Фаза 4 — Extract + Synthesis (Етап 3a) — `виконано`

Блоки 6+7 закриті: search runtime тепер працює в snippet-first режимі, extract не запускається без потреби, `fetch_page` лишився крайнім fallback, а synthesis отримує ізольований `evidence`-ввід без planner/evaluator trace. Додано reordered evidence для LLM, inline citations у фінальній відповіді, staging повний `pytest` зелений, live runtime синхронізований і smoke-probe пройдений.

### Сесія 042 — Cleanup: LLM замість regex — `виконано`

Видалено ~400 рядків hardcoded regex-патернів із пошукового шару і planner'а:

- `agent/search_task.py` — прибрано 13 regex-констант і 12 regex-функцій (SPACE_*, ENTITY_NORMALIZATIONS, NEWS/DOCS/RESEARCH/COMPOUND_QUERY_PATTERNS тощо). `_build_search_task()` повертає прості defaults; профіль/mode/recency визначає LLM planner. `_plan_with_model()` більше не перетирає LLM output через `_coerce_query_to_mode`.
- `agent/search_intent.py` — видалено повністю.
- `agent/planner.py` — `_needs_reasoning()` тільки `/think`; `_should_short_circuit()` тільки media; додано `PlannerInput.dialogue_context`.
- `core/prompts.py` — `PLANNER_SYSTEM_PROMPT` переписаний: Telegram-контекст, поступовий намір, "не підігравай". `SEARCH_COMPOSER_SYSTEM_PROMPT` доповнений правилами нормалізації сленгу.
- `app/message_logic.py` — `plan_execution()` тепер підтягує останні 6 повідомлень через `fetch_recent()` і передає в planner.

### Фаза 5 — Retry + Tests (Етап 3a)

Блоки 8+11: retry зі зміною стратегії + E2E тестова матриця.

Між кожною фазою: staging deploy, pytest, live smoke-test.

---

## Робочий Цикл Для Кожної Сесії

1. Зафіксувати ціль сесії і прив'язати до етапу/блоку.
2. Зробити артефакт що перевіряється (код, тест, документ).
3. Staging pytest зелений перед deploy в live.
4. Оновити `devlog.md`.
5. Якщо змінився стан робіт — оновити статуси в цьому `plan.md`.

## Що Не Треба Робити Раніше Часу

- Розширювати admin UI до повного control plane до стабілізації capability bindings.
- Починати memory redesign до стабільного Telegram event normalization.
- Брати повний agent framework (LangGraph, CrewAI) — custom orchestrator для нашого scope простіший. За production досвідом, для 2-4 agents з clear workflow custom 150-line orchestrator кращий за будь-який framework.
- "Покращувати" legacy код — він на шляху до архіву.

## Карта Документів

| Документ | Що містить |
|----------|------------|
| Цей `plan.md` | Статуси етапів, що зроблено, що далі, робочий спринт |
| `implementation-roadmap.md` | 11 блоків з кодом, файлами, тестами, залежностями |
| `strategy.md` | Місія, принципи, provider strategy, критерії успіху |
| `telegram-geometry.md` | Поведінкова модель геометрії повідомлень, 4 рівні реалізації |
| `routing-contract.md` | Цільовий потік, об'єкти контракту, відповідальність шарів |
| `capability-matrix.md` | Матриця capabilities з providers і цінами |
| `provider-split-schema.md` | Capability bindings з конкретними моделями |
| `search-flow.md` | Поточний vs цільовий пошуковий pipeline |
| `search-implementation-decision.md` | Provider routing matrix для search |
| `docs/research/*` | Research база з бенчмарками, цінами, patterns |
