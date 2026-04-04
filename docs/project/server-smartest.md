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
