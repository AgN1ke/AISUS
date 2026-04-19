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

### Що Вже Є Станом На 2026-04-09

- `MessageGeometry` уже несе:
  - `sender`
  - direct `reply_target`
  - `message_sent_at_*`
  - `reply_target.sent_at_*`
  - `reply_chain` як multi-hop ancestry baseline
- `app/message_logic.py` уже пише в пам'ять:
  - `[CHAT-TURN]` з sender identity
  - часові якорі
  - `reply_chain_hop_N_*`
- `build_user_task()` уже додає:
  - `[CHAT-GEOMETRY]`
  - `[PARTICIPANT-HISTORY]`

Тобто сьогоднішній geometry-пакет уже не на нулі. Найбільший незакритий залишок тут — не timestamps чи ancestry, а **справжня thread-aware memory window** для паралельних гілок у групі.

### Окреме Уточнення По Voice Conversation

Voice більше не можна трактувати як окремий “медіа-хвіст”, який не входить у діалоговий контекст. Станом на 2026-04-09 runtime уже змінено так, щоб:

- user voice без тексту ставав транскрибованою user-реплікою;
- цей транскрипт ішов не лише в `[MEDIA]`, а й у normal recent memory як `user`;
- text reply на ботівський voice не випадав із addressed/media-path.

Додатково після live-регресії 2026-04-09 зафіксовано ще один обов'язковий контракт: **voice input не повинен маршрутизуватися в `stt_voice` capability для генерації змістовної відповіді**. STT уже відбулося на media-layer, тому природний voice-turn далі має йти як звичайний діалоговий хід у `chat_final`, а голосовість відповіді визначається transport-шаром (`respond_with_voice`), а не окремою “нечатовою” моделлю.

Тобто voice conversation тепер треба розглядати як частину того ж самого geometry/dialogue layer, а не окрему утиліту поруч із `/a` та `/v`.

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

## Окремий Пакет — Capability-Level Reasoning / Thinking Mode — `задеплоєно, policy enablement pending`

Цей пакет не є косметичним покращенням. Він закриває структурний дефект поточного runtime: reasoning plumbing у коді існує, але практично не працює. Зараз у системі ще живе стара логіка з `OPENAI_REASONING_MODEL`, яка була доречна в часи окремих reasoning-моделей, але більше не відповідає сучасному стеку. Через це planner може поставити `use_reasoning=True`, а downstream runtime усе одно відправить звичайний запит без жодних reasoning-параметрів. Тобто reasoning ніби є в архітектурі, але фактично мертвий.

Проблема тут не в одному прапорці. Reasoning зараз прив’язаний до глобального env-контракту, а не до конкретних capability. Це означає, що система не може чесно відповісти на прості operational питання: для якого саме capability дозволено reasoning, який effort для нього має бути, чи підтримує поточна модель reasoning, і що робити, якщо capability вимкнений в адмінці, але planner або користувач усе одно просить "подумати глибше".

Цільовий контракт інший. Reasoning має стати не глобальною магією, а capability-level дозволом. У кожного capability, де це має сенс, повинен з’явитися власний operational state: reasoning увімкнений чи ні, і який effort дозволений. Але навіть увімкнений reasoning не означає, що кожен запит треба відправляти в дорогий thinking-mode. Це лише дозвіл на глибше міркування там, де воно справді потрібне: за явним trigger від користувача або за рішенням planner-а.

На цьому пакеті ми свідомо розводимо дві окремі речі. Перша — runtime truth: як саме `env.py`, `llm.py`, `planner.py` і transport layer повинні поводитися, коли reasoning активний або вимкнений. Друга — admin truth: як це все має відображатися в UI так, щоб користувач не міг створити невалідну конфігурацію. У першій хвилі імплементації пріоритет — runtime, а не панель керування. Немає сенсу спочатку малювати checkbox у UI, якщо сам runtime все одно ігнорує reasoning або застосовує його через мертву глобальну логіку.

### Що Вже Є

- `agent/planner.py` уже повертає `use_reasoning`, але детектор тригерів занадто вузький і прив’язаний майже тільки до `/think`.
- `agent/llm.py` має reasoning plumbing, але воно зав’язане на `reasoning_model()` і `reasoning_effort()` з глобального env.
- `core/env.py` досі живе старими helper-ами `reasoning_model()`, `reasoning_effort()` і `provider_supports_reasoning()`.
- Gemini path має тільки старий `thinkingBudget` baseline, а не повноцінне керування reasoning per request.
- Admin UI поки взагалі не має окремого capability-level контролю для reasoning.

### Що Робимо Спочатку

У першій технічній хвилі пакет reasoning закривається на рівні runtime. Конкретно:

- `core/env.py` отримує capability-level helpers:
  - чи підтримує конкретна пара `provider + model` reasoning;
  - чи дозволений reasoning для конкретного capability;
  - який effort має бути для конкретного capability.
- `agent/llm.py` перестає залежати від `OPENAI_REASONING_MODEL` і переходить на capability-based reasoning gate.
- OpenAI-compatible path має поводитися правильно:
  - reasoning-параметри додаються тільки коли reasoning реально активний;
  - при reasoning не відправляється `temperature`;
  - для reasoning-моделей не зберігається стара логіка "окрема reasoning model".
- Gemini path має отримати явний contract:
  - коли reasoning неактивний — мінімальний thinking або його вимкнення;
  - коли активний — thinking config мапиться від effort.
- `agent/planner.py` розширює trigger detection і додає capability gate, щоб planner не міг вимагати reasoning там, де capability не дозволяє його policy-wise.

### Що Робимо Після Runtime

Лише після того, як reasoning стане правдивим у runtime, є сенс рухатись у UI:

- checkbox `Reasoning` на capability;
- `Effort` select для capability;
- автоматичний disable для моделей, які reasoning не підтримують;
- валідація provider/model pair ще до збереження env.

### Стан На 2026-04-13

Перша runtime-хвиля цього пакета вже закрита локально. У `core/env.py` додано capability-level reasoning helpers, `agent/llm.py` більше не залежить від `OPENAI_REASONING_MODEL` і реально будує transport request по capability policy, а не по глобальному legacy env. Planner і direct agent-flow приведені до спільного trigger-контракту через окремий helper, тому `/think`, `подумай`, `роздумай`, `think carefully` і суміжні explicit-фрази більше не розходяться між planner та runtime.

На transport-рівні reasoning тепер поводиться по-різному, але послідовно. Для OpenAI-compatible GPT-5/o-series reasoning-параметри додаються тільки коли capability дозволяє reasoning і explicit/planner gate справді його активував; при цьому `temperature` не відправляється, а `max_tokens` переводиться у `max_completion_tokens`. Для DeepSeek reasoning більше не тримається на старій "глобальній reasoning-моделі": якщо capability дозволяє reasoning, runtime підміняє `deepseek-chat` на `deepseek-reasoner`, але не намагається підсовувати туди OpenAI-style `reasoning` kwargs. Для Gemini 3.x і 2.5 thinking config теж став capability-aware: без reasoning це мінімальний або фактично вимкнений thinking, а при reasoning-active він мапиться від effort policy.

Окремо вже додано регресії на planner gate і transport behavior. Це важливо, бо reasoning-пакет легко ламається не явним падінням, а тихим поверненням до "звичайного" запиту без reasoning. Саме тому в цій хвилі були зафіксовані тести не лише на happy-path, а й на випадок, коли planner просить reasoning, але capability policy має його вимкнути.

UI-хвиля цього пакета теж уже закрита локально. В `admin_ui.py` додано capability-level controls для reasoning: checkbox `Reasoning`, `Effort` select, server-side нормалізація значень при save і client-side disable для моделей, які reasoning не підтримують. Тобто operational surface в адмінці вже відповідає runtime truth і не дає зберегти невалідний provider/model/reasoning стан.

Staging/full pytest для цього пакета вже пройдено, а reasoning-шар синхронізовано в live разом з admin UI controls. `smartest-bot.service` і `smartest-admin.service` після цього успішно перезапущені, а `/health` admin-контур віддав `ok`.

Що свідомо ще не закрито в цьому пакеті: server-side ввімкнення reasoning policy для конкретних capability і перевірка реальної поведінки на live-конфігу після того, як reasoning flags будуть увімкнені в адмінці. Тобто код і UI вже в production-контурі, а решта — це вже не імплементація reasoning, а операційне налаштування policy.

Окремо вже закрито і перший live-regression цього пакета. Після реального ввімкнення reasoning у `chat_final` з’ясувалося, що поточний Gemini 3 path поводиться некоректно в двох місцях. Перше: explicit-команда користувача `запусти різонінг` не проходила через trigger helper, бо reasoning-фрази були закодовані зіпсовано і покривали тільки старий вузький набір слів. Друге: навіть коли reasoning фактично не активувався, runtime все одно надсилав для `gemini-3.1-pro-preview` `thinkingLevel=minimal`, а ця модель у live відповіла `400 INVALID_ARGUMENT`, що такий рівень thinking не підтримується. Це ламало весь хід ще до відповіді бота.

Після цього reasoning-контракт уточнено. Для Gemini 3 без активного reasoning `thinkingConfig` тепер узагалі не відправляється; при explicit reasoning-effort `none` більше не мапиться в `minimal`, а піднімається до `low`, щоб не вбити transport. Planner теж більше не може загубити прямий user-intent: якщо користувач явно просить reasoning і capability policy його дозволяє, `use_reasoning=True` примусово зберігається навіть якщо planner-model повернула `false`. Тобто цей пакет уже пройшов не тільки staging, а й першу реальну production-перевірку на ввімкненому reasoning.

### Критерій Закриття Першої Хвилі

- `OPENAI_REASONING_MODEL` більше не є blocking-фактором для reasoning.
- `use_reasoning=True` реально змінює transport request для capability, де reasoning дозволений і підтримується.
- `use_reasoning=True` автоматично гаситься, якщо capability policy або модель reasoning не підтримують.
- Gemini і OpenAI проходять reasoning gate через один і той самий capability-level contract, а не через випадкові окремі винятки.

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

## Пакет Live-Тесту 2026-04-08

Окремо після живого Telegram-тесту зафіксовано пакет user-facing задач, які не можна втратити між сесіями. Детальний розбір, контекст користувача, підтверджені причини по коду і логах та групування по пакетах винесено в:

- `docs/project/live-task-packet-2026-04-08.md`

Коротка карта:

- **Пакет A. Telegram Geometry + Participant Identity**  
  Пост із медіа й текстом має оброблятися як єдиний target bundle; бот має розрізняти хто саме говорить у групі, а не зливати всіх у одного `user`. Це пряме продовження Етапу 4.

- **Пакет B. Очищення Контексту / Пам'яті**  
  Потрібні `/c@botname` і кнопка на сайті для повного очищення контексту бота. Це можна тягнути fast-track, не чекаючи повного memory redesign, але треба пам'ятати що поточний `clear_all()` не чистить working/recent.
  Bare `/c` або форма `@botname /c` не повинні нічого очищати, бо в одному чаті можуть жити кілька ботів.

- **Пакет C. Voice In / Voice Out / TTS Commands**  
  Нормальний voice pipeline, відповіді голосом, `/a@botname + text`, `/v@botname`. Це окремий пакет Етапу 5, не дрібний локальний фікс.

- **Пакет D. Admin Observability / Logs**  
  Поточна сторінка логів занадто бідна. Потрібен повний trace-контур по flow/planner/media/search/memory/errors. Це в ядрі Етапу 7, але частину бажано підтягнути раніше, інакше Stage 4-5 важко діагностувати.

- **Пакет D. Admin Observability / Logs** — `частково виконано`  
  Уже піднято новий baseline:
  - `run.py` і `app/admin_ui.py` пишуть не лише в stdout/journal, а й у trace-файли через окремий logging setup;
  - admin-сторінка `/logs` тепер вміє читати `trace file` або `journalctl`, а не тільки systemd journal;
  - додано серверні фільтри по `chat_id`, `trace`, `level`, `contains`;
  - у runtime додано щільніші flow/media-логи, щоб у viewer було видно sender/reply-target/route, а не лише "початок/кінець".

  Що ще лишається відкритим у цьому пакеті:
  - окремий view для multi-line exception blocks, якщо live покаже, що простого line-filter недостатньо;
  - за потреби — ще тонші фільтри або агрегація по trace/thread.

  Що вже додатково підтверджено:
  - live deploy сторінки логів виконано;
  - `/logs` і `/logs-text` перевірені через реальну cookie-сесію на `127.0.0.1:8787`;
  - додано й перевірено фільтри `message_id` і `capability`;
  - trace viewer у live реально віддає flow/runtime записи з bot trace file.

- **Пакет C. Voice In / Voice Out / TTS Commands** — `частково виконано`  
  У canonical runtime вже є робочий baseline:
  1. `/a` озвучує текст прямо з команди;
  2. `/v` озвучує останню текстову відповідь бота з пам’яті чату;
  3. адресований voice-message тепер іде через реальний STT, а не через старий stub;
  4. відповідь на поточний voice-message відправляється голосом, а не тільки текстом.

  Що ще лишається відкритим у цьому пакеті:
  - Telegram smoke-test руками в живому чаті;
  - довести voice-output конфіг до сайту, якщо треба керувати TTS-моделлю/voice через admin UI;
  - окремо добити richer voice policy для довгих search/media відповідей, якщо live покаже потребу.

  Що вже додатково підтверджено:
  - targeted форми `/a@botname` і `/v@botname` покриті тестами;
  - voice runtime у live вже синхронізований;
  - server-side TTS -> STT probe на live проходить end-to-end через `.ogg`.

### Оновлення Після Реалізації 2026-04-08

- **Пакет A. Telegram Geometry + Participant Identity** — `частково виконано`  
  У runtime вже виправлено дві критичні речі:
  1. media target тепер формується як bundle, а не як "тільки аналіз картинки/відео";
  2. у recent memory тепер пишеться окремий `[CHAT-TURN]` event із sender/reply-target metadata, щоб груповий контекст не зливав усіх людей в одного абстрактного `user`.

- Що саме вже зроблено в коді:
  - `media/router.py` — `[MEDIA]` тепер включає `target_post_text` разом із `media_analysis` / `audio_transcript`;
  - `app/message_logic.py` — перед user message у пам'ять пишеться `[CHAT-TURN]` з `sender`, `reply_target_author`, `reply_target_text`, `target_media_kind` тощо;
  - `app/chat_geometry.py` / `app/message_logic.py` — geometry і пам'ять тепер несуть часові якорі `current_message_time_*` та `reply_target_time_*`, щоб бот бачив не лише хто що сказав, а й коли саме;
  - `agent/search_task.py` і `agent/planner.py` — історичні `[CHAT-TURN]` записи більше не губляться при побудові dialogue excerpt.

- Що ще лишається відкритим у цьому ж пакеті:
  - повноцінна thread/reply-line semantics із кількома паралельними лініями спілкування;
  - окреме явне розрізнення `instruction message` vs `target post` на рівні довготривалої пам'яті й planner contracts;
  - live smoke-test у Telegram після deploy.

- **Пакет B. Очищення Контексту / Пам'яті** — `частково виконано`  
  Fast-track пакет уже має робочий baseline:
  - `/c@botname` очищає всю пам'ять поточного чату (`recent + long-term + core`);
  - у web admin додано окремий action для глобального очищення пам'яті бота.

- Що саме вже зроблено в коді:
  - `memory/manager.py` — `clear_all(chat_id)` тепер чистить і working/recent, а не тільки long/core;
  - `memory/manager.py` — додано `clear_global()` для повного reset memory layers по всіх чатах;
  - `db/memory_repository.py` — додано явні delete helpers для `memory_recent`, `memory_long`, `memory_core`;
  - `app/message_logic.py` — додано точну чат-команду `/c@botname`;
  - `app/admin_ui.py` — додано кнопку й POST action `/clear-memory`.

- Що ще лишається відкритим у цьому пакеті:
  - live deploy і smoke-test `/c@botname` у Telegram;
  - за потреби — більш тонкий admin reset per-chat, а не тільки глобальний.

## Операційне Оновлення 2026-04-09

- Search live-stabilization додатково підтиснуто поверх поточного roadmap:
  - `agent/runner.py` більше не ріже partial-but-real evidence жорстким failure, якщо synthesis ще може дати обережну відповідь по знайденому;
  - live-сервер більше не сидить у `serper-only` режимі, а переведений на `SEARCH_PROVIDER=auto` з `SEARCH_PROVIDER_ATTEMPT_LIMIT=3`.
- Практичний наслідок:
  - якщо evidence справді нульова або junk -> clean failure лишається;
  - якщо evidence неповна, але жива -> search має йти у best-effort synthesis, а не у стандартний відлуп.
- Це не закриває стратегічний Search Phase 5, але прибирає один конкретний user-facing regression, який ламав популярні новинні кейси.

### Оновлення Пакета Thread-History Baseline 2026-04-09

- **Пакет A. Telegram Geometry + Participant Identity** — `частково виконано`
- У runtime з'явився не лише expanded reply-ланцюжок, а й thread-aware baseline:
  - `MessageGeometry` тепер несе `current_message_id` як окремий якір поточного повідомлення;
  - `app/message_logic.py` тепер збирає `[THREAD-HISTORY]` поверх recent пам'яті, використовуючи overlap між `reply_target` / `reply_chain` / `current_message_id`;
  - planner і search-шари почали бачити цей `[THREAD-HISTORY]` разом з `[CHAT-TURN]` і `[PARTICIPANT-HISTORY]`.
- Практичний результат: коли користувач продовжує конкретну reply-гілку, бот уже не дивиться тільки на весь чат як на один суцільний потік. У prompt він отримує окремий thread-зріз із релевантними пов'язаними turn-ами саме цієї лінії розмови.
- Це ще не закриває geometry повністю і лишає три великі хвости:
  - повноцінний per-thread memory window замість акцентованого per-chat recent;
  - чіткий thread assignment для випадків без явного reply-chain overlap;
  - живий Telegram smoke-test саме на паралельних гілках, а не тільки на thread-aware baseline.


## Операційне Оновлення 2026-04-09 — Recent Memory Window

- Для geometry/thread-aware baseline уточнено ключовий контракт: reply-гілка **не замінює** загальну пам'ять чату, а лише підсилює релевантний фрагмент через `[THREAD-HISTORY]`.
- Виправлено `db/memory_repository.py`: `fetch_recent(chat_id, limit=N)` тепер бере **останні** `N` повідомлень цього ж чату через descending subquery і повертає їх назад у хронологічному порядку.
- Практичний наслідок:
  - `PARTICIPANT-HISTORY`, `THREAD-HISTORY` і planner recent context більше не дивляться в найстаріший хвіст чату;
  - thread-акцент працює поверх актуальної пам'яті, а не поверх випадково старого контексту;
  - chat-scope для recent memory окремо зафіксований тестами на рівні repository query.
- Статус: виконано локально, підтверджено staging full `pytest`, задеплоєно в live.

## Операційне Оновлення 2026-04-09 — Media Temp Cleanup

- Перевірено server-side runtime поводження з тимчасовими медіа.
- Поточний стан live перед фіксом: `/tmp/aisus_media` не був засмічений, але в коді не було гарантованого cleanup для photo/audio/document downloads після обробки.
- Реалізацію доведено до правильного контракту:
  - `media/router.py` тепер чистить downloaded media paths у `finally` після media-analysis/transcription;
  - `media/downloader.py` отримав безпечний cleanup helper для файлів і порожніх піддиректорій всередині `MEDIA_TMP`;
  - `run.py` на старті виконує purge stale media files з `MEDIA_TMP`, щоб хвости після аварійного падіння теж не накопичувались.
- Що свідомо лишається без aggressive cleanup: логи. Вони збережені як операційний слід.
- Історія чату не росте безмежно файлово: short-term / long-term / core memory обмежуються бюджетами в `memory/manager.py`, а поточний live-state БД залишається малим.
- Статус: локальні таргетні тести зелені, staging full `pytest` зелений, live deploy виконано.

## Операційне Оновлення 2026-04-10 — Підтримка Telegram Кружечків

- У canonical runtime додано baseline-підтримку Telegram video notes (`кружечки`).
- Контракт реалізації:
  - кружечок не заводиться як окремий екзотичний тип, а проходить через існуючий `video` media-flow;
  - geometry класифікує `video_note` як `video`, тому reply на кружечок і mention поверх кружечка більше не губляться на етапі target detection;
  - downloader для Bot API тепер уміє завантажити `message.video_note` як `.mp4` у `MEDIA_TMP`.
- Практичний наслідок: бот має сприймати кружечки як відео-медіа, аналізувати їх і включати в контекст так само, як звичайне відео.
- Статус: локальні таргетні тести зелені, staging full `pytest` зелений, live deploy виконано.

## Окремий Плановий Пакет — Telegram Кружечки Як Повноцінний Тип Повідомлення

Поточний baseline fix закрив лише транспортну проблему: кружечки перестали губитися на вході, почали завантажуватися і проходити через video-flow. Цього недостатньо для продуктового рівня, який потрібен Smartest.

Проблема не в тому, що бот “не бачив файл”. Проблема в тому, що Telegram `video note` концептуально не дорівнює звичайному відео. Для користувача кружечок — це коротке особисте відеоповідомлення. У нього інша соціальна роль у чаті, інша очікувана довжина, інший баланс між візуальним та голосовим шаром, інший тип follow-up реплік. Якщо ми просто назвемо його `video` і на цьому зупинимося, модель буде бачити в ньому довільний ролик, а не саме “кружечок”, тобто не знатиме, що це по суті ближче до voice-message з візуальним контекстом.

### Чому Поточний Baseline Недостатній

Зараз runtime робить тільки мінімально прийнятне:
- transport і geometry визначають `video_note` як `video`;
- downloader вміє скачати кружечок;
- далі все йде через існуючий `video_understanding`.

Але цього недостатньо з трьох причин.

По-перше, у prompt-геометрії немає явної семантики “це Telegram-кружечок”. У `[MEDIA]` зараз лягає `target_media_type: video`, і для моделі кружечок не відрізняється від звичайного mp4-ролика.

По-друге, усередині кружечка майже завжди важливий голосовий шар, а не тільки візуальний. Для користувача кружечок часто є способом швидко щось сказати, а не просто щось показати. Тому розуміння кружечка повинно збиратися не лише як video summary, а як поєднання:
- що видно;
- що сказано;
- який був супровідний текст поста;
- у якій reply-ситуації це надіслано.

По-третє, UI і capability bindings зараз можуть вводити в оману. Якщо користувач вибере, наприклад, DeepSeek для тексту і GPT для іншого шару, це не означає, що будь-який провайдер магічно почне розуміти кружечки. Для кружечків треба чесно розвести, який capability за що відповідає.

### Який Має Бути Правильний Контракт

У цільовій реалізації кружечок не повинен бути “ще одним видом відео”. Він повинен бути окремою Telegram-сутністю всередині мультимодальної геометрії.

Це означає, що в службовому контексті бот має бачити не тільки `target_media_type: video`, а й окрему ознаку на кшталт:
- `telegram_media_subtype: video_note`
- `telegram_media_semantics: short_personal_video_message`

Тобто модель повинна явно розуміти, що це:
- не просто відеофайл;
- не зовнішній ролик;
- не довільний кліп;
- а коротке нативне повідомлення всередині Telegram-розмови.

Це змінює і спосіб аналізу, і тональність відповіді, і пріоритети в synthesis.

### Як Це Має Бути Розведено По Capability-Шарах

Фінальна обробка кружечка повинна складатися з трьох окремих шарів.

Перший шар — візуальне розуміння. За нього відповідає `video_understanding`. У поточному стеку реальним primary provider для цього залишається `Gemini`, бо саме він у нашій системі має придатний native video path.

Другий шар — мовлення всередині кружечка. Це не має лишатися побічним ефектом video-summary або старим stub-шляхом. Нормальний контракт тут — окремий `stt_voice` capability для витягу змісту сказаного.

Третій шар — фінальна відповідь користувачу. Це вже `chat_final`, який повинен синтезувати відповідь з урахуванням:
- візуального змісту кружечка;
- транскрипту сказаного;
- caption або тексту поста, якщо він є;
- геометрії reply-сценарію.

Отже, кружечки не потребують окремого “секретного” ключа, але вони і не зводяться до одного capability. Для них потрібна узгоджена робота вже існуючих шарів:
- `video_understanding`
- `stt_voice`
- `chat_final`

### Що Має Бути Показано В Admin UI

UI зараз не повинен створювати хибне враження, ніби будь-який вибір провайдера автоматично означає повну підтримку кружечків.

У цільовому варіанті для користувача має бути очевидно:
- який capability відповідає за visual video analysis;
- який capability відповідає за speech transcription;
- яка модель формує фінальну текстову відповідь;
- які обмеження виникають, якщо певний провайдер не має придатного video understanding.

Це потрібно не для краси, а щоб не виникало хибного відчуття “я вибрав DeepSeek, отже тепер DeepSeek має сам зрозуміти Telegram-кружечок”. Ні, так працювати не повинно.

### Етап 1. Уточнити Семантику В Geometry І Media Bundle

На цьому етапі ми не змінюємо ще весь мультимодальний pipeline, а робимо правильний контракт даних.

Що саме має з'явитися:
- явна відмітка, що target/current media є саме `video_note`, а не просто `video`;
- відображення цього в `[CHAT-GEOMETRY]` і `[MEDIA]`;
- окремий опис, що це коротке Telegram-відеоповідомлення з пріоритетом spoken content.

Результат цього етапу: навіть якщо нижчі шари ще не ідеальні, модель уже перестає бачити кружечок як абстрактний “ролик”.

### Етап 2. Розвести Video Analysis І STT Для Кружечків

На цьому етапі ми прибираємо нинішню логічну кашу, де кружечок проходить крізь video-flow без явного контракту на мовлення.

Що саме потрібно:
- зробити нормальний аудіо-шлях для кружечка через `stt_voice`;
- перестати покладатися на неявний або застарілий шлях для транскрипту;
- збирати для кружечка структурований media bundle, де візуальна частина і мовлення лежать окремо.

Результат цього етапу: кружечок перестає бути “просто відео з якимось summary” і стає двоканальним об'єктом: видно + сказано.

### Етап 3. Налаштувати Final Synthesis Під Соціальну Семантику Кружечка

Коли попередні два шари готові, треба виправити те, як модель формує відповідь.

Мета тут така: бот має сприймати кружечок не як зовнішній медіаконтент, а як особистий хід у розмові. Це означає:
- reply на кружечок повинен поводитися ближче до reply на voice-message, ніж до reply на випадкове відео;
- якщо в кружечку основний зміст — мовлення, відповіді не повинні надто опиратися тільки на візуальний summary;
- якщо користувач питає саме “що він сказав?” або “що на кружечку?”, bot має розуміти різницю між мовленнєвим та візуальним питанням.

Результат цього етапу: кружечок починає поводитися як природний Telegram-об'єкт у живому чаті, а не як технічний відеофайл.

### Етап 4. Привести До Ладу UI І Capability Constraints

Лише після того, як рантайм буде розведений правильно, треба довести до ладу admin UI.

Тут ми маємо зафіксувати для користувача:
- який провайдер реально використовується для video understanding;
- який для STT;
- який для final answer;
- де є технічні межі певних провайдерів.

Результат цього етапу: користувач бачить не абстрактні поля моделей, а реальний operational contract для кружечків.

### Критерій Закриття Цього Пакета

Пакет по кружечках можна вважати закритим тільки тоді, коли одночасно правдиві всі умови:

По-перше, reply на кружечок більше не зводиться в prompt до абстрактного `video`.

По-друге, у кружечку окремо й надійно обробляється spoken content, а не лише кадри.

По-третє, `chat_final` формує відповідь з урахуванням того, що кружечок є коротким особистим повідомленням у Telegram-розмові.

По-четверте, UI чесно показує, які capability й провайдери за це відповідають.

До цього моменту будь-яка реалізація кружечків вважається лише baseline, а не повністю завершеною підтримкою.

---

## Окремий Плановий Пакет — Генерація Подкастів Через NotebookLM Podcast API

Статус цього пакета зараз: `у роботі`.

Це не дрібна фіча на зразок ще однієї команди. Йдеться про окремий сервісний контур, який має брати не одне повідомлення, а тематичний зріз розмови, уточнювати намір користувача, збирати багатий текстовий dossier і тільки після цього відправляти матеріал у зовнішній генератор подкастів.

Після окремого дослідження зафіксовано, що для Smartest правильний зовнішній сервіс тут — не `notebooks.audioOverview`, а standalone **NotebookLM Enterprise Podcast API** (`podcasts`). Це важливо, бо наш продукт не крутиться навколо постійних Google notebooks; джерелом для подкасту має бути вже зібраний контекст Telegram-розмови. Саме тому Smartest має сам будувати preparation package, а Google-сервіс повинен працювати як downstream executor, який із цього пакета робить MP3.

Окремо зафіксовано й серверний/auth-контракт. Даних на кшталт service account email та numeric identifier недостатньо для реальної інтеграції. Для production-реалізації потрібні: підтверджений `PROJECT_ID`, увімкнений `Discovery Engine API`, роль `roles/discoveryengine.podcastApiUser`, робочий спосіб отримання OAuth access token на нашому VPS і підтверджений allowlist-доступ до Podcast API. Без цього писати бойовий executor передчасно.

Логіка майбутньої інтеграції теж уже визначена концептуально. Бот повинен спочатку розпізнати саме намір створити подкаст, а не випадкову згадку слова “подкаст”. Потім він має визначити тему за reply-геометрією або останнім релевантним контекстом, перепитати підтвердження теми, зібрати великий тематичний матеріал без втрати нюансів, витягти творчі побажання типу “один захищає гіпотезу, інший критикує”, сформувати `focus` і лише тоді запускати зовнішній job. На виході користувач має отримати не тільки MP3, а й текстовий файл із тим матеріалом, який реально пішов у генерацію.

Через це цей пакет залежить не тільки від зовнішнього Google API, а й від нашого внутрішнього стану по geometry та пам’яті. Щоб бот справді збирав матеріал “саме на цю тему”, йому потрібен уже не просто недавній chat-context, а надійний thread-aware і topic-aware retrieval. Тому реалізовувати цей пакет треба після поточної стабілізації geometry/search baseline, а не врізати його поверх сирого memory-контракту.

Детальний розбір, архітектура, поетапний план і вимоги до UI/секретів винесені в окремий документ: `docs/project/notebooklm-podcast-integration.md`.

Перший практичний етап цього пакета вже розпочато. У коді з’явився fail-closed readiness gate для NotebookLM Podcast capability, persisted pending-state для підтвердження теми подкасту на рівні чату, а також базовий серверний/UI-контур для безпечного завантаження service account JSON без потрапляння секрету в репозиторій. Це ще не генерація подкастів і не збір повного dossier, але це вже той фундамент, без якого наступні етапи були б небезпечними або хаотичними.

Практично це означає таке. Якщо користувач явно просить “зробити подкаст”, бот тепер не повинен випадково віддати такий запит у звичайний planner/search flow. Він або чесно повідомляє, що podcast-сервіс ще не готовий на цьому інстансі, або — якщо readiness підтверджено — переходить у confirmation-контур і перепитує тему. Паралельно адмінка вчиться приймати service account JSON, класти його в окреме secret-сховище поза git і показувати не фальшиву “галочку готово”, а реальний статус доступності API.

Другий практичний етап цього пакета теж уже почався. У рантаймі з’явився окремий `topic-scoped dossier builder`, який після підтвердження теми вміє зібрати не один випадковий шматок тексту, а структурований preparation package по темі: релевантні turn-и з recent-пам’яті, акценти користувача, тематично дотичні core facts і long-memory summaries. Це ще не зовнішній виклик у Google і не готовий MP3, але це вже той внутрішній матеріал, без якого downstream executor не матиме що якісно озвучувати. Окремо зафіксовано, що цей dossier теж є похідною пам’яттю чату, тому `/c@botname` має чистити не лише `recent/long/core`, а й pending-state та вже зібраний podcast dossier.

## Додаткове Уточнення До Podcast-Пакета

Для цього сервісу окремо зафіксовано жорсткий activation contract: поки в UI і на сервері не заповнено та не підтверджено весь operational minimum, podcast-сервіс має лишатися повністю неактивним. Не можна допускати часткового існування цього capability, коли кнопка вже є, planner уже бачить новий route, а downstream executor ще неготовий. У такому стані сервіс повинен бути відсутнім не тільки для користувача, а й для внутрішньої архітектури runtime: без route, без prompt-presence і без напівживих fallback-сценаріїв.

### Оновлення 2026-04-10: Album Support Baseline

Окремим пакетом у плані зафіксовано початкову підтримку Telegram-альбомів як єдиного media-bundle. Цей baseline вже не зводить addressed album до випадкового single target: runtime збирає sibling elements через `media_group_id` / `grouped_id`, mixed `photo+video` album route-иться через video-aware capability, а в `[MEDIA]` потрапляє структурований album-block з caption, порядком елементів, типом кожного елемента, аналізом кожного елемента і транскриптом для відео, якщо він є.

## Оновлення Після Фіксу Album Runtime Crash

- У live було відтворено конкретний краш на addressed album flow: альбом визначався правильно, але PTB `telegram.Message` падав на спробі записати службовий `_smartest_media_route_kind` прямо в об'єкт повідомлення.
- Контракт media-router вирівняно: `handle_ptb_mention()` і `handle_telethon_mention()` тепер повертають пару `(instruction_text, media_kind)` замість побічного запису службового стану в raw message object.
- Під це оновлено регресійні тести для media/message/voice сценаріїв, щоб фікс не зламав existing voice-flow і reply geometry.
- Після локального таргетного пакета повний `pytest` на staging знову зелений, а той самий код уже задеплоєно в live.

## Оновлення Після One-Shot Album Execution Fix

- Після live-перевірки підтверджено, що album bundle вже збирався, але бот усе ще відповідав на кожен Telegram update усередині одного `media_group_id` окремо.
- Причина була не в media-analysis, а в execution layer: не вистачало one-shot gating для addressed album updates.
- Додано album processing claim/finish contract у `media/album_registry.py`: перший addressed item бере `media_group` у роботу, чекає коротке settle-вікно на добір sibling-елементів і лише один раз запускає весь album flow.
- Наступні updates того самого `media_group_id` більше не запускають повторну відповідь, а логуються як duplicate skip.
- На це додано окремий regression test для message-flow, щоб сценарій `3 елементи альбому -> 1 відповідь` більше не ламався наступними змінами.
