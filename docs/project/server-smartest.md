# Контур Smartest На Сервері

Дата: `2026-04-03`

## Поточна Схема

- тестовий контур: `/opt/smartest-staging`
- основний ізольований контур: `/opt/smartest`
- Linux-користувач: `smartest`
- bot-сервіс: `smartest-bot.service`
- admin-сервіс: `smartest-admin.service`
- локальний admin host/port: `127.0.0.1:8787`
- публічний admin URL: `https://smartest.klawa.top`
- стан bot-сервісу: `loaded`, `disabled`, `active (running)` станом на цю сесію
- стан admin-сервісу: `loaded`, `enabled`, `active (running)` станом на цю сесію

## Основні Шляхи

- код застосунку: `/opt/smartest/app`
- віртуальне середовище: `/opt/smartest/venv`
- env-файл: `/opt/smartest/.env`
- логи: `/opt/smartest/logs`
- тимчасові медіа: `/opt/smartest/tmp`
- сесії: `/opt/smartest/sessions`

## База Даних

- рушій: `MariaDB`
- база даних: `smartest_db`
- користувач БД: `smartest`
- місце зберігання паролів: `/opt/smartest/.env`

## Нотатки По Рантайму

- постійний контур ізольований від `comixator`;
- `Caddy` уже змінено лише для Smartest: `smartest.klawa.top` проксується на `127.0.0.1:8787`;
- `PM2` не змінювався;
- сервіс бота використовується для Telegram smoke-test через polling;
- у `/opt/smartest/.env` тимчасово записані тестові ключі, надані користувачем у межах цієї сесії; у документації самі секрети не дублюються;
- у `/opt/smartest/.env` уже задано окремі admin-параметри для `smartest-admin.service`, включно із секретом сесії; самі секрети в документації не дублюються;
- HTTP-admin застосунок уже реалізований і працює як окремий stdlib-сервіс без нових Python-залежностей;
- код у `/opt/smartest/app` уже синхронізований із фіксом адресного бар'єра для групового чату:
  - бот не повинен відповідати на всі повідомлення поспіль;
  - базовий дозволений trigger на цьому етапі: `private`, `@mention`, `reply` на повідомлення бота.
- у тому ж серверному контурі вже задеплоєно перший керований search baseline:
  - явні search-запити більше не залежать повністю від tool-call поведінки моделі;
  - runtime сам запускає web search, збирає evidence і лише потім синтезує відповідь з джерелами.
- admin UI читає і зберігає `/opt/smartest/.env`, а також може за чекбоксом перезапускати `smartest-bot.service`.

## Корисні Команди

```bash
systemctl status smartest-bot
systemctl status smartest-admin
systemctl start smartest-bot
systemctl stop smartest-bot
journalctl -u smartest-bot -n 100 --no-pager
journalctl -u smartest-admin -n 100 --no-pager
curl http://127.0.0.1:8787/health
sudo -u smartest /opt/smartest/venv/bin/python /opt/smartest/app/run.py
```

## Наступні Кроки

1. Після smoke-test вирішити, які ключі лишаються постійними, а які треба ротейтнути й замінити.
2. Розширити admin UI від простого env-редактора до стабільнішого конфігураційного шару з валідацією capability bindings.
3. Вирішити, які поля мають лишитися прямим env-контрактом, а які треба винести в окрему керовану конфігурацію поверх provider registry.

## Оновлення Станом На Цю Сесію

- У кодовій базі підготовлено перший planner/router baseline для канонічного runtime.
- В основний контур уже синхронізовано такі файли:
  - `/opt/smartest/app/core/env.py`
  - `/opt/smartest/app/agent/llm.py`
  - `/opt/smartest/app/agent/planner.py`
  - `/opt/smartest/app/agent/runner.py`
  - `/opt/smartest/app/app/message_logic.py`
- Також синхронізовано операційні документи:
  - `/opt/smartest/app/docs/project/plan.md`
  - `/opt/smartest/app/docs/project/devlog.md`
  - `/opt/smartest/app/docs/project/server-smartest.md`
- `smartest-bot.service` після цього перезапущено й підтверджено як `active`.
- Staging-контур перед деплоєм у main пройшов:
  - `pytest tests/test_030_agent.py tests/test_031_planner.py tests/test_060_message_logic.py -q`;
  - повний `pytest -q`.
- Цей baseline не змінює мережевий контур сервера і не зачіпає `Caddy`, `PM2` чи інші проєкти на VPS.

## Оновлення Після Contextual Search Composer

- У search runtime з'явився окремий `search_task` / query-composer baseline.
- Для неоднозначних реплік типу `ну загугли` search route тепер може будувати `resolved_query` із короткого діалогового зрізу, а не лише з останнього повідомлення.
- Також прибрано дублювання поточного user message з executor context, щоб великі моделі не бачили той самий запит двічі.
- Після синхронізації цього шару треба окремо перевірити в живому контурі:
  - що explicit search не регресував;
  - що contextual search follow-up у Telegram починає поводитися краще;
  - що `smartest-bot.service` лишається `active` після оновлення.

## Оновлення Після Evaluator/Retry Baseline

- У live-контур `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/search_task.py`
  - `/opt/smartest/app/agent/runner.py`
- У search runtime тепер є control-plane `SearchEvaluation` baseline:
  - один search step оцінюється окремо від фінальної відповіді;
  - retry-loop обмежений `<= 3` ітераціями;
  - службові рішення evaluator не підмішуються в prompt фінального responder-а.
- Перед синхронізацією в live staging-контур пройшов:
  - `pytest tests/test_030_agent.py tests/test_031_planner.py tests/test_032_search_task.py tests/test_060_message_logic.py -q` -> `17 passed`;
  - повний `pytest -q` -> `26 passed`.
- Після деплою `smartest-bot.service` перезапущено й підтверджено як `active`.
- Операційний журнал `journalctl -u smartest-bot.service` зафіксував успішний restart `2026-04-03 14:30:21`.

## Оновлення Після Provider Registry Baseline

- У live-контур `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/core/env.py`
  - `/opt/smartest/app/core/provider_registry.py`
  - `/opt/smartest/app/agent/llm.py`
  - `/opt/smartest/app/agent/planner.py`
  - `/opt/smartest/app/agent/runner.py`
  - `/opt/smartest/app/agent/search_task.py`
  - `/opt/smartest/app/memory/summarizer.py`
  - `/opt/smartest/app/media/vision.py`
- Runtime тепер має capability-level transport baseline:
  - `ProviderBinding`;
  - `CAPABILITY_<NAME>_PROVIDER`;
  - `CAPABILITY_<NAME>_ADAPTER`;
  - `CAPABILITY_<NAME>_MODEL`;
  - `PROVIDER_<NAME>_API_KEY`;
  - `PROVIDER_<NAME>_BASE_URL`.
- Це ще не native multi-provider runtime. Реально активний adapter class поки що один: OpenAI-compatible transport для `openai_chat` / `openai_vision`.
- Перед синхронізацією в live staging-контур пройшов:
  - `pytest tests/test_030_agent.py tests/test_031_planner.py tests/test_032_search_task.py tests/test_033_provider_registry.py tests/test_060_message_logic.py -q` -> `20 passed`;
  - повний `pytest -q` -> `29 passed`.
- Після деплою `smartest-bot.service` перезапущено й підтверджено як `active`.
- `bot.log` зафіксував штатний startup після цього оновлення:
  - `runtime.boot`
  - `runtime.db_bootstrap_ok`
  - `runtime.instances_loaded`
  - `telegram_bot.start`
  - `telegram_bot.polling_started`

## Оновлення Після Search Hardening

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/search_task.py`
  - `/opt/smartest/app/agent/tools/web_search.py`
  - `/opt/smartest/app/agent/runner.py`
- `smartest-bot.service` після search hardening перезапущено й підтверджено як `active`.
- На `/opt/smartest-staging` перед цим пройшло:
  - таргетний `pytest -q tests/test_032_search_task.py tests/test_030_agent.py tests/test_034_web_search.py` -> `14 passed`;
  - повний `pytest -q` -> `35 passed`.
- Live-probes після деплою:
  - `що нового в OpenAI сьогодні` -> осмислена відповідь із джерелами;
  - colloquial follow-up search більше не йде в junk-domain dump, а маршрутизується через `llm_composer`.

## Оновлення Після Structured Search Provider Layer

- У live `/opt/smartest/.env` `SEARCH_PROVIDER` переведено на `auto`.
- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/search_task.py`
  - `/opt/smartest/app/agent/runner.py`
  - `/opt/smartest/app/agent/tools/web_search.py`
  - `/opt/smartest/app/.env-example`
- `smartest-bot.service` після цього перезапущено й підтверджено як `active`.
- Live-probe після деплою показав:
  - `what is new in OpenAI today` -> `SearchTask(mode=news, recency_days=2)` і осмислена відповідь із джерелами;
  - structured composer/runtime тепер передає search capability не тільки `query`, а й policy hints (`mode`, `recency_days`, `preferred_domains`).

## Оновлення Після Native Gemini Adapter Baseline

- На `/opt/smartest-staging` синхронізовано:
  - `/opt/smartest-staging/agent/llm.py`
  - `/opt/smartest-staging/core/env.py`
  - `/opt/smartest-staging/core/provider_registry.py`
  - `/opt/smartest-staging/media/vision.py`
  - `/opt/smartest-staging/memory/summarizer.py`
  - `/opt/smartest-staging/tests/test_033_provider_registry.py`
  - `/opt/smartest-staging/tests/test_036_gemini_adapter.py`
- Staging verification після цього пройшла:
  - таргетний `pytest -q tests/test_033_provider_registry.py tests/test_036_gemini_adapter.py tests/test_040_media_router.py tests/test_030_agent.py` -> зелений;
  - повний `pytest -q` -> зелений.
- Окремий staging smoke-test із тестовим `GEMINI_API_KEY` підтвердив:
  - native text call через `gemini_generate_content` -> `TEXT=Hello`;
  - native vision path через `media.vision.describe_images(...)` -> непорожній опис валідного PNG.
- Практичний нюанс, зафіксований у runtime:
  - для `gemini-2.5-flash` при малому `max_tokens` довелося явно задавати `thinkingBudget=0`, інакше API витрачав токени на thinking і повертав порожній текст без користувацької відповіді.
- Після staging verification кодовий baseline також синхронізовано в live `/opt/smartest/app`:
  - `/opt/smartest/app/agent/llm.py`
  - `/opt/smartest/app/core/env.py`
  - `/opt/smartest/app/core/provider_registry.py`
  - `/opt/smartest/app/media/vision.py`
  - `/opt/smartest/app/memory/summarizer.py`
  - `/opt/smartest/app/.env-example`
- `smartest-bot.service` після цього перезапущено й підтверджено як `active`.
- Live-контур після цього все одно не переведено на Gemini як default provider. Це навмисно: кодовий baseline готовий, але live бот поки лишається на наявному transport-конфігу до окремого рішення про capability bindings.

## Оновлення Після Chat Geometry + Gemini Search Fix

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/adapters/base.py`
  - `/opt/smartest/app/app/chat_geometry.py`
  - `/opt/smartest/app/app/message_logic.py`
  - `/opt/smartest/app/media/router.py`
  - `/opt/smartest/app/agent/search_task.py`
  - `/opt/smartest/app/agent/runner.py`
  - `/opt/smartest/app/agent/tools/web_search.py`
- У live `/opt/smartest/.env` додано:
  - `PROVIDER_GEMINI_API_KEY`
  - `SEARCH_GEMINI_MODEL=gemini-2.5-flash`
- Після цього `smartest-bot.service` перезапущено й підтверджено як `active`.
- Що саме це закриває:
  - `reply_to_bot + current photo/video` більше не має брати старе повідомлення бота як media target;
  - `reply_to_media + text prompt` тепер має брати саме тегнуте медіа як target;
  - search у live більше не сидить лише на порожньому HTML fallback, якщо доступний Gemini key.
- Live probe після цього підтвердив:
  - `search_web("OpenAI latest news")` у live повертає 5 grounded results через новий retrieval path.

## Оновлення Після Мінімальної Адмін-Панелі

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/app/admin_ui.py`
  - `/opt/smartest/app/deploy/smartest-admin.service`
  - `/opt/smartest/app/deploy/smartest-admin.caddy`
  - `/opt/smartest/app/.env-example`
- У live `/opt/smartest/.env` додано й оновлено:
  - `SMARTEST_ADMIN_USERNAME`
  - `SMARTEST_ADMIN_PASSWORD`
  - `SMARTEST_ADMIN_SESSION_SECRET`
  - `SMARTEST_ADMIN_HOST`
  - `SMARTEST_ADMIN_PORT`
  - `SMARTEST_MANAGED_SERVICE`
  - `SMARTEST_ADMIN_SERVICE_NAME`
- На сервері встановлено окремий systemd unit `smartest-admin.service`, увімкнено `enable` і підтверджено `active`.
- У `Caddy` додано окремий Smartest-only блок:
  - `smartest.klawa.top -> reverse_proxy 127.0.0.1:8787`
- Перевірка після деплою:
  - `curl http://127.0.0.1:8787/health` -> `ok`
  - `curl -I https://smartest.klawa.top/login` -> `HTTP/2 200`
  - live login flow повертає cookie `smartest_admin_session` і відкриває dashboard.
- `comixator`, його каталог, його PM2-процеси і його Caddy-маршрути не змінювалися.

## Оновлення Після Закриття Блоку 3 (`Query Planner`)

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/runner.py`
  - `/opt/smartest/app/agent/search_task.py`
  - `/opt/smartest/app/core/prompts.py`
- `smartest-bot.service` після цього перезапущено й підтверджено як `active`.
- На staging `/opt/smartest-staging` перед live-sync пройшло:
  - `python -m pytest -q tests/test_030_agent.py tests/test_032_search_task.py --noconftest` -> `21 passed`
  - повний `python -m pytest -q --color=no` -> `78 passed`
- Live smoke-check query planner без звернення до БД підтвердив:
  - `plan_search_queries("порівняй новини про OpenAI і Anthropic", ...)` -> `2` sub-queries
  - sub-queries:
    - `OpenAI` / `news`
    - `Anthropic` / `news`
- Це означає, що comparison-запити в live більше не злипаються в один загальний query, а йдуть у decomposition baseline.
## Оновлення Після Закриття Блоків 4+5 (`Parallel Search` + `Smart Evaluation`)

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/runner.py`
  - `/opt/smartest/app/agent/search_task.py`
  - `/opt/smartest/app/agent/tools/web_search.py`
  - `/opt/smartest/app/agent/search_intent.py`
  - `/opt/smartest/app/core/prompts.py`
  - `/opt/smartest/app/docs/project/plan.md`
  - `/opt/smartest/app/docs/project/devlog.md`
- `smartest-bot.service` після цього перезапущено і підтверджено як `active`.
- На staging `/opt/smartest-staging` перед live-sync пройшов повний:
  - `python -m pytest -q --color=no` -> зелений повний suite
- Що саме тепер є в live runtime:
  - sub-query search йде через `asyncio.gather()`, а не послідовний task-loop;
  - coverage оцінюється per sub-query;
  - retry запускається тільки для конкретного gap;
  - provider routing короткий і profile-aware (`Brave` / `Exa` / `Tavily`).
## Оновлення Після Search Regression Fix

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/tools/web_search.py`
  - `/opt/smartest/app/agent/runner.py`
- `smartest-bot.service` після цього перезапущено й підтверджено як `active`.
- Що саме виправлено в live runtime:
  - fallback для `search_web()` більше не зупиняється на перших двох відсутніх search-провайдерах;
  - якщо `Brave/Serper` недоступні, runtime доходить до `openai_search`, а при timeout — до `gemini_search`;
  - agent tool-loop більше не падає на `NormalizedResult` при серіалізації tool result.
- Підтверджені live probes:
  - `search_web("NASA Moon mission latest news", 5, 7, mode="news", profile="news")` -> `5` grounded results;
  - `run_agent("Пошукай там піндоси на місяць полетіли чи шо")` -> релевантна відповідь про `Artemis II` з джерелами.
## Оновлення Після Search Memory Integration

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/app/message_logic.py`
  - `/opt/smartest/app/agent/runner.py`
  - `/opt/smartest/app/core/prompts.py`
- `smartest-bot.service` після цього перезапущено й підтверджено як `active`.
- Що саме змінилося в live runtime:
  - адресовані користувацькі тексти в media-turn’ах більше не губляться до запису в пам’ять;
  - explicit search після виконання пише в пам’ять системний блок `[SEARCH]`;
  - follow-up chat turns бачать цей `[SEARCH]` як частину пам’яті й можуть відповідати, що саме бот щойно шукав.
- Підтверджений live probe на окремому `chat_id`:
  - `Пошукай там піндоси на місяць полетіли чи шо`
  - `Скажи, що ти шукав нещодавно?`
  - результат: follow-up коректно посилається на щойно виконаний search, а не каже, що бот “не може шукати в реальному часі”.

## Оновлення Після Закриття Фази 4 (`Selective Extract` + `Synthesis Isolation`)

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/runner.py`
  - `/opt/smartest/app/agent/tools/fetch_page.py`
  - `/opt/smartest/app/core/prompts.py`
  - `/opt/smartest/app/core/telegram_formatting.py`
- `smartest-bot.service` після цього перезапущено і підтверджено як `active`.
- На staging `/opt/smartest-staging` перед live-sync пройшов повний:
  - `python -m pytest -q --color=no` -> зелений повний suite
- Що саме змінилося в live runtime:
  - search synthesis більше не бачить planner trace, planned queries і evaluator chatter;
  - evidence перед synthesis reorder-иться під LLM і йде як окремий numbered evidence payload;
  - фінальна відповідь використовує inline citations із прихованими посиланнями замість старого блоку `Джерела:`;
  - targeted retry спочатку може підняти extract для проблемного sub-query, а вже потім змінювати query;
  - `fetch_page` лишився крайнім fallback і працює з явним timeout/user-agent rotation.
- Live smoke-probe на окремому `chat_id` підтвердив:
  - релевантну відповідь на `Пошукай там піндоси на місяць полетіли чи шо`;
  - наявність inline citation link у фінальному тексті;
  - `smartest-bot.service` після probe лишився `active`.

## Оновлення Після Видалення Окремого Фактчекерного Режиму

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/search_task.py`
  - `/opt/smartest/app/agent/tools/web_search.py`
  - `/opt/smartest/app/core/prompts.py`
  - `/opt/smartest/app/app/admin_ui.py`
  - `/opt/smartest/app/.env-example`
  - оновлені project/research docs і тести
- `smartest-bot.service` і `smartest-admin.service` після цього перезапущено та підтверджено як `active`.
- На staging `/opt/smartest-staging` перед live-sync пройшов повний:
  - `.venv/bin/python -m pytest -q --color=no` -> зелений повний suite
- У live runtime тепер:
  - немає окремого search-profile для перевірки тверджень;
  - запити типу `перевір`, `чи правда`, `ну загугли` мають йти через звичайний Google-like web-search rewrite;
  - репозиторій у `/opt/smartest/app` без кешів більше не містить згадок цього старого режиму.

## Оновлення Після Синхронізації Live Runtime 2026-04-08

- У `/opt/smartest/app` залито актуальний runtime-код із локального репозиторію, а не лише окремі точкові фікси.
- Перед live-sync staging `/opt/smartest-staging` повністю синхронізовано з поточним репо і прогнано:
  - `.venv/bin/python -m pytest -q --color=no` -> зелений повний suite
- Після sync перезапущено:
  - `smartest-bot.service`
  - `smartest-admin.service`
- Поточний live-стан:
  - `smartest-bot.service` -> `active`
  - `smartest-admin.service` -> `active`
- Додатково перевірено на сервері:
  - у `/opt/smartest/app/app/message_logic.py` є `_is_clear_context_command`
  - у `/opt/smartest/app/app/message_logic.py` є `flow.memory_cleared`
  - `memory_manager.select_context()` після `clear_all()` повертає `[CONTEXT-STATE]` з явною забороною вигадувати стару історію чату

## Оновлення Після Voice Baseline Sync 2026-04-09

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/media/voice.py`
- `smartest-bot.service` після цього перезапущено і підтверджено як `active`.
- Додатково перевірено server-side audio probe на live runtime:
  - TTS генерує `.ogg` voice output;
  - STT читає цей `.ogg` через той самий runtime-контур;
  - probe з українським текстом повернув коректний transcript.
- Практичний висновок:
  - voice runtime технічно живий у live;
  - наступний крок по пакету C — уже Telegram smoke-test руками, а не ще один server-side bootstrap fix.

## Оновлення Після Live Verify `/logs` 2026-04-09

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/app/admin_ui.py`
- `smartest-admin.service` після цього перезапущено і підтверджено як `active`.
- Додатково перевірено через live HTTP session на `127.0.0.1:8787`:
  - `/health` -> `200 ok`
  - `/login` -> успішний session redirect
  - `/logs` -> `200`
  - `/logs-text` -> `200`
- У live logs viewer тепер підтверджено:
  - trace-file reading працює;
  - є фільтри `chat_id`, `trace`, `level`, `contains`, `message_id`, `capability`;
  - `logs-text?message_id=252483` реально звужує вивід до конкретного bot update line.

## Оновлення Після Search Best-Effort Sync 2026-04-09

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/runner.py`
- На staging `/opt/smartest-staging` перед live-sync пройшов повний:
  - `.venv/bin/python -m pytest -q --color=no` -> зелений full suite
- У live `/opt/smartest/.env` змінено:
  - `SEARCH_PROVIDER=auto`
  - `SEARCH_PROVIDER_ATTEMPT_LIMIT=3`
- `smartest-bot.service` після цього перезапущено і підтверджено як `active`.
- Що саме змінилося в live runtime:
  - partial evidence більше не відсікається жорстким failure, якщо вона виглядає живою і не junk;
  - search synthesis тепер може дати best-effort відповідь із явною невизначеністю;
  - live retrieval більше не pinned на `serper-only` і може проходити через fallback providers.
- Додатково перевірено окремим server-side retrieval probe:
  - проблемні Hezbollah/Lebanon news-style queries після env-switch уже повертали `5` результатів;
  - у цьому кейсі фактичний live fallback спрацював через `openai_search`.
- Виявлене обмеження:
  - `Brave` у поточному live-контурі повертає `422` на протестовані кириличні news queries, тому поки що реальна сила live-search у цьому сценарії тримається на fallback layer.

## Оновлення Після Geometry Time Anchors 2026-04-09

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/adapters/base.py`
  - `/opt/smartest/app/app/chat_geometry.py`
  - `/opt/smartest/app/app/message_logic.py`
- На staging `/opt/smartest-staging` перед live-sync пройшов повний:
  - `.venv/bin/python -m pytest -q --color=no` -> зелений full suite
- `smartest-bot.service` після цього перезапущено і підтверджено як `active`.
- Що саме змінилося в live runtime:
  - `MessageGeometry` тепер несе часові якорі поточного повідомлення й reply-target;
  - `[CHAT-GEOMETRY]` і `[CHAT-TURN]` тепер містять `current_message_time_*` та `reply_target_time_*`;
  - live-логи `flow.geometry` тепер теж показують `msg_time` і `reply_target_time`.

## Оновлення Після Reply-Chain Baseline 2026-04-09

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/adapters/base.py`
  - `/opt/smartest/app/app/chat_geometry.py`
  - `/opt/smartest/app/app/message_logic.py`
- На staging `/opt/smartest-staging` перед live-sync пройшов повний:
  - `.venv/bin/python -m pytest -q --color=no` -> зелений full suite
- `smartest-bot.service` після цього перезапущено і підтверджено як `active`.
- Що саме змінилося в live runtime:
  - `MessageGeometry` тепер несе `reply_chain` як multi-hop ancestry baseline;
  - `[CHAT-GEOMETRY]` містить `reply_chain_depth` і `reply_chain_hop_N_*`;
  - `[CHAT-TURN]` у пам'яті теж пише ancestry-hops, а не тільки один `reply_target`.

## Оновлення Після Voice Conversation Memory Fix 2026-04-09

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/media/router.py`
  - `/opt/smartest/app/app/message_logic.py`
- На staging `/opt/smartest-staging` перед live-sync пройшов повний:
  - `.venv/bin/python -m pytest -q --color=no` -> зелений full suite
- `smartest-bot.service` після цього перезапущено і підтверджено як `active`.
- Що саме змінилося в live runtime:
  - voice/audio router тепер повертає semantic transcript, а не лише `[MEDIA]` bundle;
  - user voice без тексту може лягати в recent memory як нормальна user-репліка;
  - text reply на ботівський voice лишається в addressed/media-flow і не має випадати в ignore-path.

## Оновлення Після Voice Planner Route Fix 2026-04-09

- У live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/agent/planner.py`
- Перед live-sync на staging `/opt/smartest-staging` пройшло:
  - `.venv/bin/python -m pytest -q --color=no` -> зелений full suite
- `smartest-bot.service` після цього перезапущено і підтверджено як `active`.
- Що саме виправлено в live runtime:
  - natural `voice/audio` reply-turn більше не маршрутизується в `stt_voice` capability для генерації змістовної відповіді;
  - voice transcript, отриманий на media-layer, тепер далі обробляється як звичайний chat-turn через `chat_final`;
  - transport layer і надалі може відправити відповідь голосом, якщо `respond_with_voice=True`.
- Причина фіксу:
  - у live trace було підтверджено, що voice-повідомлення не ігнорувалося, а падало після planner decision на `stt_voice` з `404 This is not a chat model`.

## Оновлення Пакета Thread-History Baseline 2026-04-09

- На staging `/opt/smartest-staging` синхронізовано:
  - `/opt/smartest-staging/adapters/base.py`
  - `/opt/smartest-staging/app/chat_geometry.py`
  - `/opt/smartest-staging/app/message_logic.py`
  - `/opt/smartest-staging/agent/planner.py`
  - `/opt/smartest-staging/agent/search_task.py`
  - `/opt/smartest-staging/tests/test_061_message_logic_layers.py`
  - `/opt/smartest-staging/tests/test_064_participant_history.py`
- Перед live-sync на staging прогнано:
  - `.venv/bin/python -m pytest -q --color=no` -> зелений full suite
- Потім код у live `/opt/smartest/app` синхронізовано:
  - `/opt/smartest/app/adapters/base.py`
  - `/opt/smartest/app/app/chat_geometry.py`
  - `/opt/smartest/app/app/message_logic.py`
  - `/opt/smartest/app/agent/planner.py`
  - `/opt/smartest/app/agent/search_task.py`
  - оновлено project docs у репозиторії
- `smartest-bot.service` і `smartest-admin.service` після deploy перезапущено та підтверджено як `active`.
- На рівні логіки у live runtime:
  - `MessageGeometry` тепер несе `current_message_id`;
  - `[CHAT-GEOMETRY]` включає цей message anchor;
  - `build_user_task()` додає `[THREAD-HISTORY]` для reply-гілки на основі overlap між message-id ancestry;
  - planner і search control-plane більше не ігнорять цей thread-зріз у своїх excerpt-ах.


## Оновлення Після Recent Memory Window Fix 2026-04-09

- У live-контур `/opt/smartest/app` задеплоєно фікс `db/memory_repository.py`.
- `fetch_recent(chat_id, limit=N)` більше не бере найстаріший хвіст пам'яті; тепер live geometry/planner/search працюють з останнім recent window поточного чату.
- Перевірка перед live deploy:
  - staging `/opt/smartest-staging` -> повний `pytest -q --color=no` зелений.
- Після deploy:
  - `smartest-bot.service` перезапущено;
  - статус `active` підтверджено через `systemctl is-active smartest-bot.service`.

## Оновлення Після Media Temp Cleanup 2026-04-09

- На live перевірено `/tmp/aisus_media`: під час аудиту там було `0` файлів.
- Після цього в live-контур задеплоєно cleanup-фікс:
  - runtime тепер чистить downloaded media files після обробки;
  - на старті виконується purge stale media temp files.
- Після restart `smartest-bot.service`:
  - сервіс `active`;
  - `/tmp/aisus_media` лишився порожнім (`4.0K` директорія, `0` files).
- Логи залишені без aggressive cleanup навмисно.

## Оновлення Після Підтримки Кружечків 2026-04-10

- У live-контур `/opt/smartest/app` задеплоєно baseline-підтримку Telegram video notes.
- `smartest-bot.service` перезапущено після синхронізації:
  - статус `active` підтверджено.
- Практичний ефект live:
  - PTB/runtime бачить `video_note` як `video` media target;
  - Bot API downloader може завантажити кружечок для подальшого video-analysis flow.

## Оновлення Після Першого Етапу NotebookLM Podcast 2026-04-10

- У staging `/opt/smartest-staging` синхронізовано й прогнано повний `pytest -q --color=no` після додавання podcast baseline:
  - `app/podcast_intent.py`
  - `core/podcast.py`
  - `db/migrations/004_podcast_state.sql`
  - оновлені `app/message_logic.py`, `app/admin_ui.py`, `db/settings_repository.py`
  - нові тести `tests/test_072_podcast_integration.py` і `tests/test_073_podcast_message_flow.py`
- Після staging verification той самий пакет синхронізовано в live `/opt/smartest/app`.
- На live встановлено додаткову залежність `google-auth` у `/opt/smartest/venv`.
- Після deploy перезапущено:
  - `smartest-bot.service`
  - `smartest-admin.service`
- Поточний live-стан після перевірки:
  - `systemctl is-active smartest-bot.service` -> `active`
  - `systemctl is-active smartest-admin.service` -> `active`
  - `curl -fsS http://127.0.0.1:8787/health` -> `ok`
- Що саме з'явилося в live runtime:
  - fail-closed readiness gate для NotebookLM Podcast capability;
  - persisted pending-state для підтвердження теми подкасту на рівні конкретного чату;
  - secure upload/check контур у адмінці для service account JSON без збереження самого секрету в `.env` чи git.
- Що ще важливо:
  - цей етап не вмикає реальну генерацію подкастів;
  - capability має лишатися неактивною, поки readiness-check не підтвердить повну готовність Google-контуру;
  - server-side status panel в адмінці тепер має показувати реальний стан доступності API, а не фальшиве "готово".

## Оновлення Після Другого Етапу NotebookLM Podcast 2026-04-10

- У staging `/opt/smartest-staging` синхронізовано:
  - `/opt/smartest-staging/app/podcast_dossier.py`
  - `/opt/smartest-staging/app/message_logic.py`
  - `/opt/smartest-staging/db/settings_repository.py`
  - `/opt/smartest-staging/db/migrations/005_podcast_dossier.sql`
  - оновлені тести `tests/test_060_message_logic.py`, `tests/test_073_podcast_message_flow.py`, `tests/test_074_podcast_dossier.py`
- Перед live-sync на staging пройшов повний `.venv/bin/python -m pytest -q --color=no` -> зелений full suite.
- Після цього в live `/opt/smartest/app` синхронізовано той самий podcast dossier пакет.
- `smartest-bot.service` після deploy перезапущено і підтверджено як `active`.
- Окремо перевірено бойову БД:
  - `migrations_log` містить `005_podcast_dossier.sql`, тобто нова міграція реально застосувалася.
- Що саме це дало в live runtime:
  - confirmation-потік подкасту тепер може зібрати і зберегти `topic-scoped dossier`;
  - `/c@botname` чистить не лише message-memory, а й pending/dossier стан подкастів;
  - подкастний пакет просунувся вперед навіть попри те, що сам Google `podcasts` endpoint поки лишається недоступним.

## Оновлення Після Фіксу Telegram `text_mention` 2026-04-10

- На staging `/opt/smartest-staging` синхронізовано:
  - `/opt/smartest-staging/app/chat_geometry.py`
  - `/opt/smartest-staging/tests/test_063_geometry_dates.py`
- Перед live-sync на staging прогнано `.venv/bin/python -m pytest -q --color=no` -> зелений full suite.
- Після цього зміни перенесено в live `/opt/smartest/app`.
- `smartest-bot.service` після deploy перезапущено й підтверджено як `active`.
- Що це дало:
  - live-контур більше не ігнорує звернення, коли Telegram передає згадку як hidden `text_mention`, а не як буквальне `@botname` у тексті.

## Оновлення Після Live-Фіксу Capability Bindings 2026-04-10

- У live `/opt/smartest/.env` критичні capability повернуто з невалідного Gemini на OpenAI:
  - `chat_final`
  - `planner_reasoning`
  - `search_synthesis`
  - `search_query_planner`
  - `search_query_composer`
  - `search_evaluator`
  - `memory_summary`
  - `vision_image`
  - `video_understanding`
  - `document_context`
- Причина: `PROVIDER_GEMINI_API_KEY` був невалідний, через що live-runtime падав з `API_KEY_INVALID`, хоча addressed-повідомлення вже доходили до runtime і проблема більше не була в Telegram geometry.
- Після live-конфіг фіксу `smartest-bot.service` перезапущено й підтверджено як `active`.
- Додатково прогнано live sanity-check через `run_simple(..., capability="chat_final")`, щоб переконатися, що бот реально повертає текстову відповідь.

## Оновлення Після Фіксу Ignored Edited Updates 2026-04-10

- На staging `/opt/smartest-staging` синхронізовано:
  - `/opt/smartest-staging/adapters/telegram_bot.py`
  - `/opt/smartest-staging/tests/test_067_telegram_bot_adapter.py`
- Перед live-sync на staging прогнано `.venv/bin/python -m pytest -q --color=no` -> зелений full suite.
- Після цього зміни перенесено в live `/opt/smartest/app`.
- `smartest-bot.service` після deploy перезапущено й підтверджено як `active`.
- Що це дало:
  - live-контур більше не реагує на редаговані повідомлення в Telegram.

## Оновлення Після Live-Фіксу Video Reply Regression 2026-04-10

- На staging `/opt/smartest-staging` синхронізовано:
  - `/opt/smartest-staging/media/voice.py`
  - `/opt/smartest-staging/media/video.py`
  - `/opt/smartest-staging/media/router.py`
  - `/opt/smartest-staging/tests/test_040_media_router.py`
  - `/opt/smartest-staging/tests/test_041_video_pipeline.py`
- Перед live-sync на staging прогнано `.venv/bin/python -m pytest -q --color=no` -> зелений full suite.
- Після цього зміни перенесено в live `/opt/smartest/app`.
- `smartest-bot.service` після deploy перезапущено й підтверджено як `active`.
- Що це дало:
  - live-контур у сценарії `reply -> video -> targeted question` більше не губить аудіозміст через stub-транскрипцію;
  - у `[MEDIA]` для відео тепер з’являється `audio_transcript`, якщо він витягнувся.

## Оновлення Після Live-Фіксу Album Support 2026-04-10

- На staging `/opt/smartest-staging` синхронізовано album/media пакет:
  - `/opt/smartest-staging/adapters/base.py`
  - `/opt/smartest-staging/adapters/telegram_bot.py`
  - `/opt/smartest-staging/adapters/userbot.py`
  - `/opt/smartest-staging/media/album_registry.py`
  - `/opt/smartest-staging/media/downloader.py`
  - `/opt/smartest-staging/media/router.py`
  - `/opt/smartest-staging/app/message_logic.py`
  - `/opt/smartest-staging/core/prompts.py`
  - `/opt/smartest-staging/tests/test_040_media_router.py`
  - `/opt/smartest-staging/tests/test_041_video_pipeline.py`
  - `/opt/smartest-staging/tests/test_061_message_logic_layers.py`
  - `/opt/smartest-staging/tests/test_068_album_registry.py`
- Перед live-sync на staging прогнано `.venv/bin/python -m pytest -q --color=no` -> зелений full suite.
- Після цього зміни перенесено в live `/opt/smartest/app`.
- `smartest-bot.service` після deploy перезапущено й підтверджено як `active`.
- Що це дало:
  - live-контур почав трактувати Telegram-альбоми як media bundle;
  - reply/mention на елемент альбому підтягує не один випадковий файл, а весь пост;
  - mixed `photo+video` album більше не обрізається до першого елемента.

## Оновлення Після Album Crash Fix

- У live-контурі `/opt/smartest/app` усунуто album runtime crash, який падав на addressed media-group через спробу записати службове поле в PTB `Message`.
- Після фіксу staging-контур знову пройшов повний `pytest -q --color=no` без регресій.
- У live після синхронізації коду `smartest-bot.service` перезапущено й підтверджено як `active`.

## Оновлення Після One-Shot Album Execution Fix

- У live `/opt/smartest/app` задеплоєно execution-fix для Telegram-альбомів: один `media_group_id` більше не повинен породжувати кілька відповідей від бота.
- У runtime додано явні album execution logs: `flow.album_claimed` і `flow.album_skip_duplicate`.
- Перед деплоєм staging-контур знову пройшов повний `pytest -q --color=no`; після деплою `smartest-bot.service` перезапущено й підтверджено як `active`.

## 2026-04-11 — Admin UI / video capability
- У live задеплоєно фікс `app/admin_ui.py`, який нормалізує несумісні capability bindings у панелі керування.
- `video_understanding` тепер відображається тільки з допустимими Gemini-моделями і не зберігає OpenAI-моделі для video input.
- `smartest-admin.service`: active.
- `http://127.0.0.1:8787/health`: ok.

## 2026-04-13 — Reasoning package deploy
- У staging `/opt/smartest-staging` reasoning-пакет пройшов повний `.venv/bin/python -m pytest -q --color=no`.
- Окремо під час staging verification синхронізовано `media/vision.py`, бо staging ще жив на старішому файлі й ламав не reasoning-логіку, а старий expectation у `tests/test_036_gemini_adapter.py`.
- У live `/opt/smartest/app` синхронізовано:
  - `core/env.py`
  - `core/reasoning.py`
  - `agent/llm.py`
  - `agent/planner.py`
  - `agent/runner.py`
  - `app/admin_ui.py`
  - `media/vision.py`
  - `docs/project/plan.md`
  - `docs/project/devlog.md`
- Після deploy перезапущено:
  - `smartest-bot.service`
  - `smartest-admin.service`
- Live verification:
  - `smartest-bot.service` -> `active`
  - `smartest-admin.service` -> `active`
  - `curl http://127.0.0.1:8787/health` -> `ok`
- Практичний результат:
  - reasoning runtime уже є в production-контурі;
  - capability-level reasoning controls уже доступні в admin UI;
  - наступний operational крок — вирішити, для яких capability reasoning реально вмикати і з яким effort.

## 2026-04-13 — Reasoning live hotfix

- Після першого live-тесту з увімкненим reasoning знайдено і закрито production regression у `chat_final`:
  - explicit-команда `запусти різонінг` не проходила через trigger helper;
  - Gemini 3 path падав на `400 INVALID_ARGUMENT`, бо runtime відправляв `thinkingLevel=minimal`, який `gemini-3.1-pro-preview` у live не приймає.
- У staging `/opt/smartest-staging` синхронізовано:
  - `core/reasoning.py`
  - `core/env.py`
  - `agent/planner.py`
  - `tests/test_031_planner.py`
  - `tests/test_075_reasoning_runtime.py`
- Після цього staging знову пройшов повний `.venv/bin/python -m pytest -q --color=no` -> зелений.
- Після staging reasoning hotfix синхронізовано і в live `/opt/smartest/app`, `smartest-bot.service` перезапущено й підтверджено як `active`.
- Live sanity-check через локальний `run_simple()` на нейтральному запиті пройшов: runtime більше не падає на `thinkingLevel=minimal`.
- Поточний live config після цього такий:
  - `CAPABILITY_PLANNER_REASONING_REASONING_ENABLED=1`
  - `CAPABILITY_CHAT_FINAL_REASONING_ENABLED=""`
  - тобто planner reasoning увімкнений, а фінальна відповідь ще не переведена в reasoning-mode policy-wise.

## 2026-04-13 — Voice command timeout hotfix

- У staging `/opt/smartest-staging` синхронізовано:
  - `app/message_logic.py`
  - `media/voice.py`
  - `tests/test_076_voice_command_fallback.py`
- Після цього staging знову пройшов повний `.venv/bin/python -m pytest -q --color=no` -> зелений.
- Що саме виправлено:
  - `/a` і `/v` більше не повинні скидати в чат повний текст при помилці voice transport;
  - PTB voice send тепер іде з розширеними timeout-ами (`read/write/connect/pool`), щоб зменшити кількість фальшивих timeout-ів на надсиланні voice reply.

## 2026-04-18 — Multitenant Stage 4 deploy (`/model` + user_settings binding)

- У staging `/opt/smartest-staging` виконано повний branch-sync, бо старий staging-контур уже не містив `billing/` і не міг дати чесний сигнал по multitenant runtime.
- Після синхронізації staging пройшов повний `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `billing/bootstrap.py`
  - `billing/commands.py`
  - `core/provider_registry.py`
  - `core/model_preferences.py`
  - `adapters/telegram_bot.py`
  - `app/message_logic.py`
  - `docs/project/multitenant-plan.md`
  - `docs/project/devlog.md`
- Перед розпакуванням live-коду створено rollback backup: `/opt/smartest/app.prev`.
- Додатково синхронізовано `/opt/smartest/docs` із `app/docs`, щоб серверні markdown-нотатки не роз’їжджались із кодом.
- Після deploy перезапущено:
  - `smartest-bot.service`
  - `smartest-admin.service`
- Live verification:
  - `smartest-bot.service` -> `active`
  - `smartest-admin.service` -> `active`
  - `curl http://127.0.0.1:8787/health` -> `ok`
  - `billing/commands.py` і `core/model_preferences.py` присутні в `/opt/smartest/app`
- Практичний результат:
  - `/model` і `/settings` тепер дають inline-вибір моделей у Telegram;
  - вибір користувача реально застосовується в runtime через `BillingContext.meta["user_settings"]`;
  - наступний великий блок після цього — `Stage 4.5A` admin dashboard.

## 2026-04-18 — Multitenant Stage 4.5A admin users slice

- У staging `/opt/smartest-staging` синхронізовано тільки цей admin slice:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
  - `tests/test_071_admin_ui.py`
  - `tests/test_088_admin_repository.py`
  - `tests/test_089_admin_dashboard.py`
- Після точкового sync staging пройшов **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
- Для rollback збережено попередні копії:
  - `/opt/smartest/app.prev/app/admin_ui.py`
  - `/opt/smartest/app.prev/db/admin_repository.py`
  - `/opt/smartest/app.prev/docs/project/devlog.md`
  - `/opt/smartest/app.prev/docs/project/multitenant-plan.md`
- Після deploy перезапущено тільки `smartest-admin.service` (бот не чіпався).
- Live verification:
  - `smartest-admin.service` -> `active`
  - `curl http://127.0.0.1:8787/health` -> `ok`
  - `GET /admin/users` без сесії -> `303 /login`
  - `/opt/smartest/app/db/admin_repository.py` присутній
  - `/opt/smartest/app/app/admin_ui.py` присутній
- Практичний результат:
  - працює `/admin/users`
  - працює `/admin/users/<id>`
  - працює `POST /admin/users/<id>/credit`
  - Stage 4.5A більше не нульовий, але `/admin/transactions`, `/admin/chats`, `/admin/topups`, `/admin/keys` ще не реалізовані

## 2026-04-18 — Multitenant Stage 4.5A admin transactions

- У staging `/opt/smartest-staging` синхронізовано наступний admin slice:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
  - `tests/test_090_admin_transactions.py`
- Після точкового sync staging знову пройшов **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
- Для rollback оновлено backup у `/opt/smartest/app.prev` для цього slice.
- Після deploy перезапущено тільки `smartest-admin.service`.
- Live verification:
  - `smartest-admin.service` -> `active`
  - `curl http://127.0.0.1:8787/health` -> `ok`
  - `GET /admin/transactions` без сесії -> `303 /login`
  - `/opt/smartest/app/db/admin_repository.py` присутній
  - `/opt/smartest/app/app/admin_ui.py` присутній
- Практичний результат:
  - працює `/admin/transactions`
  - Stage 4.5A вже має global transactions visibility
  - з незакритого лишаються `/admin/chats`, `/admin/topups`, `/admin/keys`

## 2026-04-18 — Multitenant Stage 4.5A admin chats

- У staging `/opt/smartest-staging` синхронізовано наступний admin slice:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
  - `tests/test_091_admin_chats.py`
- Після точкового sync staging знову пройшов **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
- Для rollback оновлено backup у `/opt/smartest/app.prev` для цього slice.
- Після deploy перезапущено тільки `smartest-admin.service`.
- Live verification:
  - `smartest-admin.service` -> `active`
  - `curl http://127.0.0.1:8787/health` -> `ok`
  - `GET /admin/chats` без сесії -> `303 /login`
  - `/opt/smartest/app/db/admin_repository.py` присутній
  - `/opt/smartest/app/app/admin_ui.py` присутній
- Практичний результат:
  - працює `/admin/chats`
  - Stage 4.5A має chats overview з owner, policy і spend-метриками
  - з незакритого лишаються `/admin/topups`, `/admin/keys`

## 2026-04-18 — Multitenant Stage 4.5A admin topups

- У staging `/opt/smartest-staging` синхронізовано наступний admin slice:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
  - `docs/project/server-smartest.md`
  - `tests/test_092_admin_topups.py`
- Після точкового sync staging знову пройшов **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
  - `docs/project/server-smartest.md`
- Для rollback оновлено backup у `/opt/smartest/app.prev` для цього slice.
- Після deploy перезапущено тільки `smartest-admin.service`.
- Live verification:
  - `smartest-admin.service` -> `active`
  - `curl http://127.0.0.1:8787/health` -> `ok`
  - `GET /admin/topups` без сесії -> `303 /login`
  - `/opt/smartest/app/db/admin_repository.py` присутній
  - `/opt/smartest/app/app/admin_ui.py` присутній
- Практичний результат:
  - працює `/admin/topups`
  - Stage 4.5A уже має audit trail не тільки по витратах, а й по поповненнях
  - з незакритого лишається `/admin/keys`

## 2026-04-18 — Multitenant Stage 2 keypool runtime integration

- У staging `/opt/smartest-staging` синхронізовано runtime slice:
  - `core/provider_registry.py`
  - `billing/keypool.py`
  - `billing/gateway.py`
  - `agent/llm.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
  - `docs/project/server-smartest.md`
  - `tests/test_033_provider_registry.py`
  - `tests/test_082_billing_gateway.py`
- Після точкового sync staging прогнано **повний** `.venv/bin/python -m pytest -q --color=no`.
- У live `/opt/smartest/app` задеплоєно:
  - `core/provider_registry.py`
  - `billing/keypool.py`
  - `billing/gateway.py`
  - `agent/llm.py`
  - multitenant docs
- Для rollback оновлено backup у `/opt/smartest/app.prev` для цього slice.
- Після deploy перезапущено:
  - `smartest-bot.service`
  - `smartest-admin.service`
- Live verification:
  - bot/admin сервіси `active`
  - `/health` -> `ok`
  - runtime не падає без seed-нутого keypool, бо `.env` лишається fallback
- Практичний результат:
  - Stage 2 більше не зависає в стані "keypool написаний, але не підключений"
  - `ProviderBinding` тепер несе `key_id/key_source`
  - транзакції можуть бути прив'язані до конкретного `provider_keys.id`
  - 429 / auth-failures тепер оновлюють стан keypool

## 2026-04-18 — Multitenant Stage 4.5A admin keys

- У staging `/opt/smartest-staging` синхронізовано останній admin slice Stage 4.5A:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `db/keypool_repository.py`
  - `tests/test_093_admin_keys.py`
  - `docs/project/devlog.md`
  - `docs/project/multitenant-plan.md`
  - `docs/project/server-smartest.md`
- Після sync staging прогнано **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `app/admin_ui.py`
  - `db/admin_repository.py`
  - `db/keypool_repository.py`
  - multitenant docs
- Для rollback оновлено backup у `/opt/smartest/app.prev` для цього slice.
- Перезапущено `smartest-admin.service`.
- Live verification:
  - `smartest-admin.service` -> `active`
  - `curl http://127.0.0.1:8787/health` -> `ok`
  - `GET /admin/keys` без сесії -> `303 /login`
  - add/toggle routes зареєстровані в live-коді
- Практичний результат:
  - Stage 4.5A закрито повністю
  - працює `/admin/keys`
  - key pool можна seed-ити й переводити між `active` / `disabled` прямо через адмінку
  - ручний re-enable більше не зависає на старому cooldown, бо `set_key_status(..., 'active')` чистить `cooldown_until`

## 2026-04-19 — Multitenant §12.3 Part A async bridge

- У staging `/opt/smartest-staging` синхронізовано runtime slice:
  - `app/message_logic.py`
  - `agent/runner.py`
  - `agent/search_task.py`
  - `billing/gateway.py`
  - `memory/summarizer.py`
  - `memory/importance.py`
  - `memory/reflection.py`
  - `tests/test_094_concurrent_llm.py`
- Після sync staging прогнано **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно той самий runtime slice.
- Для rollback оновлено backup змінених файлів у `/opt/smartest/app.prev`.
- Перезапущено `smartest-bot.service`.
- Live verification:
  - `smartest-bot.service` -> `active`
  - systemd journal після рестарту не показав негайного traceback
- Практичний результат:
  - Частина А з `multitenant-plan.md §12.3` закрита
  - sync `chat_once` більше не викликається напряму з async execution path у planner/message flow, runner/search flow, gateway і memory background
  - додано concurrency regression `tests/test_094_concurrent_llm.py`

## 2026-04-19 — Multitenant §12.3 Part B DB pool + executor sizing

- У staging `/opt/smartest-staging` синхронізовано:
  - `core/env.py`
  - `db/connection.py`
  - `run.py`
  - `.env-example`
  - `tests/test_095_runtime_sizing.py`
  - multitenant docs
- У staging `.env` виставлено:
  - `DB_POOL_SIZE=50`
  - `LLM_THREAD_POOL_SIZE=128`
- Після sync staging прогнано **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `core/env.py`
  - `db/connection.py`
  - `run.py`
  - `.env-example`
  - multitenant docs
- У live `.env` виставлено:
  - `DB_POOL_SIZE=50`
  - `LLM_THREAD_POOL_SIZE=128`
- Для rollback оновлено backup у `/opt/smartest/app.prev` для цього slice.
- Після deploy перезапущено:
  - `smartest-bot.service`
- Live verification:
  - `smartest-bot.service` -> `active`
  - `curl http://127.0.0.1:8787/health` -> `ok`
  - `/opt/smartest/.env` містить `DB_POOL_SIZE=50` і `LLM_THREAD_POOL_SIZE=128`
  - негайного traceback після restart нема
- Практичний результат:
  - Частина Б з `multitenant-plan.md §12.3` закрита
  - runtime піднімається з явним default executor sizing замість implicit Python default
  - DB pool більше не живе на старому maxsize=10

## 2026-04-19 — Multitenant billing correctness: pricing seed + Gemini usage

- На staging `/opt/smartest-staging` синхронізовано:
  - `billing/pricing_seed.py`
  - `db/bootstrap.py`
  - `agent/llm.py`
  - `billing/gateway.py`
  - `scripts/seed_pricing.py`
  - `tests/test_036_gemini_adapter.py`
  - `tests/test_082_billing_gateway.py`
  - `tests/test_096_pricing_seed.py`
  - `tests/conftest.py`
- Після sync staging прогнано **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно runtime slice:
  - `billing/pricing_seed.py`
  - `db/bootstrap.py`
  - `agent/llm.py`
  - `billing/gateway.py`
  - `scripts/seed_pricing.py`
- Для rollback оновлено backup тих самих файлів у `/opt/smartest/app.prev`.
- Перезапущено:
  - `smartest-bot.service`
- Live verification:
  - `smartest-bot.service` -> `active`
  - `/opt/smartest/.env` містить валідні DB credentials для live-контуру
  - прямий probe через `bootstrap_db()` + `SELECT COUNT(*) FROM pricing` -> `pricing_rows=27`
- Практичний результат:
  - `pricing` більше не лишається порожньою після bootstrap
  - `scripts/seed_pricing.py` більше не робить подвійний seed-прохід
  - Gemini usage extraction тепер враховує `thoughtsTokenCount`, а reasoning-виклики не падають у `0 / 0`

## 2026-04-19 — Multitenant keypool-first policy for billed turns

- На staging `/opt/smartest-staging` синхронізовано:
  - `core/provider_registry.py`
  - `tests/test_033_provider_registry.py`
- Після sync staging прогнано **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `core/provider_registry.py`
- Для rollback оновлено backup цього файлу в `/opt/smartest/app.prev`.
- Перезапущено:
  - `smartest-bot.service`
- Live verification:
  - `smartest-bot.service` -> `active`
  - billed turn path більше не маскує env як звичайний binding source
  - якщо keypool порожній, binding маркується як `env_fallback`, а не просто `env`
- Практичний результат:
  - keypool тепер primary для billed turns
  - env лишився лише контрольованим fallback
  - `key_id` attribution більше не губиться тихо там, де provider_keys уже доступний

## 2026-04-19 — Multitenant `/balance` sub-transaction breakdown

- На staging `/opt/smartest-staging` синхронізовано:
  - `db/transactions_repository.py`
  - `billing/commands.py`
  - `tests/test_086_billing_commands.py`
  - multitenant docs
- Після sync staging прогнано **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `db/transactions_repository.py`
  - `billing/commands.py`
  - multitenant docs
- Для rollback оновлено backup змінених runtime-файлів у `/opt/smartest/app.prev`.
- Перезапущено:
  - `smartest-bot.service`
- Live verification:
  - `smartest-bot.service` -> `active`
  - `/balance` більше не містить stage-заглушку про breakdown
  - тепер підтримуються `/balance last` і `/balance turn <id>` для деталізації turn-а
- Практичний результат:
  - user-facing billing transparency у Telegram доведена до базового робочого стану
  - breakdown будується тільки в межах акаунта, без ризику показати чужий turn по довільному id

## 2026-04-19 — Multitenant voice/persona settings in Telegram

- На staging `/opt/smartest-staging` синхронізовано:
  - `core/runtime_user_settings.py`
  - `core/user_preferences.py`
  - `core/prompts.py`
  - `core/provider_registry.py`
  - `media/voice.py`
  - `billing/commands.py`
  - multitenant docs
- Після sync staging прогнано **повний** `.venv/bin/python -m pytest -q --color=no` -> зелений.
- У live `/opt/smartest/app` задеплоєно:
  - `core/runtime_user_settings.py`
  - `core/user_preferences.py`
  - `core/prompts.py`
  - `core/provider_registry.py`
  - `media/voice.py`
  - `billing/commands.py`
  - multitenant docs
- Для rollback оновлено backup змінених runtime-файлів у `/opt/smartest/app.prev`.
- Перезапущено:
  - `smartest-bot.service`
- Live verification:
  - `smartest-bot.service` -> `active`
  - TTS runtime більше не читає голос тільки з `OPENAI_VOCALIZER_VOICE`: user-level `voice_id` override підтримується
  - prompt-layer більше не живе тільки на global persona: `persona_slug` підмішується в runtime persona override
- Практичний результат:
  - `/settings` і `/model` у Telegram тепер дають окремі inline menus для `voice_id` і `persona_slug`
  - обидва значення зберігаються в `user_settings` і реально впливають на runtime, а не лишаються декоративними
