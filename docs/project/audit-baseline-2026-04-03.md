# Базовий Аудит

Дата: 2026-04-03

## Обсяг

Це базовий технічний аудит актуального репозиторію після оновлення до `origin/gpt_wiser`.

Мета:

- відокремити реальну робочу архітектуру від історичних шарів;
- звірити фактичний runtime з поточними deployment artifacts;
- зафіксувати доведені дефекти й архітектурні розриви;
- створити базу для наступного стабілізаційного етапу.

Секрети користувача в цей документ не заносяться. Використовуються лише назви env-змінних і структурні висновки.

## Підсумок

У репозиторії зараз співіснують дві різні системи:

- `legacy`-лінія на [main.py](/C:/Python_projects/Smartest/main.py#L11) і `src/*`;
- `new runtime`-лінія на [run.py](/C:/Python_projects/Smartest/run.py#L33), `adapters/*`, `app/*`, `agent/*`, `media/*`, `memory/*`, `db/*`.

Проблема не лише в історичному шумі. Репозиторій реально знаходиться в split-brain стані:

- deployment files досі запускають legacy-лінію;
- tests і нові модулі орієнтовані на new runtime;
- конфігураційний контракт у цих двох ліній різний;
- у новому runtime є вже вбудовані merge-корупції й доведені runtime-bugs.

Найважливіший висновок:

- спочатку треба вибрати один канонічний runtime;
- після цього стабілізувати саме його;
- іншу лінію або архівувати, або видалити.

## Що Виглядає Як Цільова Майбутня Архітектура

### Новий Рантайм

Основний контур нової архітектури:

- [run.py](/C:/Python_projects/Smartest/run.py#L33) — async entrypoint;
- [adapters/telegram_bot.py](/C:/Python_projects/Smartest/adapters/telegram_bot.py#L12) — PTB adapter;
- [adapters/userbot.py](/C:/Python_projects/Smartest/adapters/userbot.py#L14) — Telethon adapter;
- [app/message_logic.py](/C:/Python_projects/Smartest/app/message_logic.py#L28) — unified message flow;
- [agent/runner.py](/C:/Python_projects/Smartest/agent/runner.py#L95) — agent/simple routing;
- [media/router.py](/C:/Python_projects/Smartest/media/router.py#L26) — reply-to-media path;
- [memory/manager.py](/C:/Python_projects/Smartest/memory/manager.py#L18) — recent/long memory;
- [db/bootstrap.py](/C:/Python_projects/Smartest/db/bootstrap.py#L5) — DB init+migrations.

Ця лінія вже ближча до цільової архітектури:

- є unified message abstraction;
- є окремий memory layer;
- є окремий media layer;
- є зачатки agent/search flow;
- є окрема DB-модель для knowledge/memory/settings/search cache.

### Ознаки Того, Що Тести Ціляться В Новий Рантайм

- [tests/test_030_agent.py](/C:/Python_projects/Smartest/tests/test_030_agent.py#L2) тестує `agent.runner`;
- [tests/test_060_message_logic.py](/C:/Python_projects/Smartest/tests/test_060_message_logic.py#L3) тестує `app.message_logic`;
- CI у [.github/workflows/tests.yml](/C:/Python_projects\\Smartest/.github/workflows/tests.yml#L31) запускає `pytest`, тобто орієнтується на новий модульний контур.

## Що Досі Лишається Фактичним Шляхом Деплою

Deployment-артефакти досі запускають legacy-лінію:

- [Procfile](/C:/Python_projects/Smartest/Procfile#L1) -> `python main.py`
- [Dockerfile](/C:/Python_projects/Smartest/Dockerfile#L22) -> `python main.py`
- [docker-compose.yml](/C:/Python_projects/Smartest/docker-compose.yml#L8) передає старі env-поля і не узгоджений з новим runtime.

Тобто репозиторій одночасно:

- розвиває нову архітектуру;
- але продовжує деплоїти стару.

## Розрив У Контракті Конфігурації

### Контракт Legacy Env

Legacy-шар читає:

- `MYAPI_BOT_TOKEN`
- `OPENAI_GPT_MODEL`
- `OPENAI_TTS_MODEL`
- `OPENAI_WHISPER_MODEL`
- `OPENAI_VOCALIZER_VOICE`
- `FILE_PATHS_AUDIO_FOLDER`

Див. [src/heroku_config_parser.py](/C:/Python_projects/Smartest/src/heroku_config_parser.py#L14).

### Контракт Env Для Нового Рантайму

Новий runtime читає:

- `TG_BOT_TOKEN`
- `OPENAI_CHAT_MODEL`
- `OPENAI_REASONING_MODEL`
- `CHAT_JOIN_PASSWORD`
- `VISION_MODEL`
- `SEARCH_PROVIDER` і provider keys
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`
- `INSTANCES_CONFIG`

Див. [run.py](/C:/Python_projects/Smartest/run.py#L7), [agent/llm.py](/C:/Python_projects/Smartest/agent/llm.py#L7), [db/connection.py](/C:/Python_projects/Smartest/db/connection.py#L20), [media/vision.py](/C:/Python_projects/Smartest/media/vision.py#L6), [agent/tools/web_search.py](/C:/Python_projects/Smartest/agent/tools/web_search.py#L8).

### Важлива Невідповідність

Наданий користувачем `.env` узгоджується головно з legacy-лінією, а не з `run.py`.

Особливо критично:

- new runtime чекає `TG_BOT_TOKEN`, а legacy — `MYAPI_BOT_TOKEN`;
- new runtime чекає `OPENAI_CHAT_MODEL`, а legacy — `OPENAI_GPT_MODEL`;
- `OPENAI_BASE_URL` і `OPENAI_API_MODE` зараз ніде не використовуються;
- new runtime вимагає DB-контур уже на старті через [db/bootstrap.py](/C:/Python_projects/Smartest/db/bootstrap.py#L5);
- default [config/instances.yaml](/C:/Python_projects/Smartest/config/instances.yaml#L1) містить плейсхолдери, а не робочий production fallback.

## Знахідки

### Критичні

#### 1. Рантайм У Стані Split-Brain: шлях деплою й цільова архітектура роз'їхалися

Докази:

- [Procfile](/C:/Python_projects/Smartest/Procfile#L1)
- [Dockerfile](/C:/Python_projects/Smartest/Dockerfile#L22)
- [run.py](/C:/Python_projects/Smartest/run.py#L33)
- [tests/test_060_message_logic.py](/C:/Python_projects/Smartest/tests/test_060_message_logic.py#L3)

Наслідок:

- не існує єдиного канонічного runtime;
- будь-яка стабілізація зараз може випадково лагодити "не ту" лінію.

#### 2. `run_agent` у новому рантаймі реально поламаний

Докази:

- у [agent/runner.py](/C:/Python_projects/Smartest/agent/runner.py#L65) є одна версія `run_agent`;
- у [agent/runner.py](/C:/Python_projects/Smartest/agent/runner.py#L95) її перекриває інша;
- друга версія використовує `use_reasoning`, який у ній не визначений: [agent/runner.py](/C:/Python_projects/Smartest/agent/runner.py#L104), [agent/runner.py](/C:/Python_projects/Smartest/agent/runner.py#L163).

Runtime reproduction:

- локально відтворено `NameError: name 'use_reasoning' is not defined` при виклику `run_agent` зі stubbed memory layer.

Наслідок:

- агентний/search path у новому runtime не можна вважати робочим.

#### 3. `media/video.py` має корупцію після merge і реально падає в другій половині конвеєра

Докази:

- повторні imports і повторні визначення функцій: [media/video.py](/C:/Python_projects/Smartest/media/video.py#L3), [media/video.py](/C:/Python_projects/Smartest/media/video.py#L31)
- повторна обробка після cleanup: [media/video.py](/C:/Python_projects/Smartest/media/video.py#L121), [media/video.py](/C:/Python_projects/Smartest/media/video.py#L128)

Runtime reproduction:

- локально відтворено `FileNotFoundError` після того, як функція видаляє `video_path`, а потім повторно намагається його обробити.

Наслідок:

- video analysis path у поточному стані не є надійним.

### Високий Пріоритет

#### 4. `media/router.py` змішує правильні кроки з явно некоректною логікою

Докази:

- дубльовані imports: [media/router.py](/C:/Python_projects/Smartest/media/router.py#L3), [media/router.py](/C:/Python_projects/Smartest/media/router.py#L5)
- дубльовані voice/audio branches: [media/router.py](/C:/Python_projects/Smartest/media/router.py#L47), [media/router.py](/C:/Python_projects/Smartest/media/router.py#L60)
- після аудіо-транскрипції код переходить до `analyze_video` на тому ж audio path: [media/router.py](/C:/Python_projects/Smartest/media/router.py#L59), [media/router.py](/C:/Python_projects/Smartest/media/router.py#L114)

Наслідок:

- reply-to-audio / reply-to-voice path у нинішньому вигляді ненадійний;
- media semantics уже є, але їх реалізація частково пошкоджена merge-шумом.

#### 5. Legacy `src/message_handler.py` є корумпованим після merge і не підходить як база подальшої роботи

Докази:

- один `async def handle_message`: [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L88)
- п'ять окремих `def _handle_message`: [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L261), [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L297), [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L334), [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L352), [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L370)
- багаторазово продубльована auth-логіка: [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L109), [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L133), [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L157), [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L181), [src/message_handler.py](/C:/Python_projects/Smartest/src/message_handler.py#L204)

Наслідок:

- цей файл не треба "лікувати косметично";
- якщо legacy-лінія не буде обрана канонічною, її простіше архівувати, ніж підтримувати.

#### 6. Новий рантайм не може бути використаний як простий drop-in replacement для наданого env

Докази:

- [run.py](/C:/Python_projects/Smartest/run.py#L13) чекає `TG_BOT_TOKEN`;
- [run.py](/C:/Python_projects/Smartest/run.py#L37) читає `config/instances.yaml`;
- [config/instances.yaml](/C:/Python_projects/Smartest/config/instances.yaml#L4) містить плейсхолдери;
- [db/bootstrap.py](/C:/Python_projects/Smartest/db/bootstrap.py#L5) обов'язково стартує БД;
- [db/connection.py](/C:/Python_projects/Smartest/db/connection.py#L22) чекає DB env.

Наслідок:

- "просто переключити деплой на `run.py`" зараз не можна без окремого стабілізаційного етапу.

### Середній Пріоритет

#### 7. `src/config_reader.py` є заглушкою без реального сенсу для рантайму

Докази:

- [src/config_reader.py](/C:/Python_projects/Smartest/src/config_reader.py#L1)

Наслідок:

- файл лише додає шум і створює хибне враження альтернативного конфіг-шару.

#### 8. Локальне середовище не відповідає `requirements.txt`

Докази:

- у [requirements.txt](/C:/Python_projects/Smartest/requirements.txt#L10) є `beautifulsoup4`;
- локально `bs4` відсутній;
- `pytest` падає на import-time через `ModuleNotFoundError: No module named 'bs4'`.

Наслідок:

- локальні прогони зараз не можна трактувати як репрезентативний стан репозиторію без перевстановлення залежностей;
- CI може пройти, а локальна копія при цьому бути в stale env.

#### 9. `requirements.txt` уже сам по собі має ознаки неохайного merge

Докази:

- дублікати `telethon` і `pyyaml`: [requirements.txt](/C:/Python_projects/Smartest/requirements.txt#L13), [requirements.txt](/C:/Python_projects/Smartest/requirements.txt#L16), [requirements.txt](/C:/Python_projects/Smartest/requirements.txt#L20), [requirements.txt](/C:/Python_projects/Smartest/requirements.txt#L24)

Наслідок:

- ще один індикатор, що кілька гілок було злиті без clean-up.

## Поточна Функціональна Карта

### Що Вже Існує В Якійсь Формі

- unified message abstraction: [adapters/base.py](/C:/Python_projects/Smartest/adapters/base.py#L8)
- bot + userbot adapters: [adapters/telegram_bot.py](/C:/Python_projects/Smartest/adapters/telegram_bot.py#L12), [adapters/userbot.py](/C:/Python_projects/Smartest/adapters/userbot.py#L14)
- DB-backed recent + long memory: [memory/manager.py](/C:/Python_projects/Smartest/memory/manager.py#L18)
- thread tracking in DB: [knowledge/threads.py](/C:/Python_projects/Smartest/knowledge/threads.py#L44)
- glossary extraction: [knowledge/glossary.py](/C:/Python_projects/Smartest/knowledge/glossary.py#L39)
- pluggable search provider layer: [agent/tools/web_search.py](/C:/Python_projects/Smartest/agent/tools/web_search.py#L13)
- image understanding: [media/vision.py](/C:/Python_projects/Smartest/media/vision.py#L13)
- first-pass video analysis pipeline: [media/video.py](/C:/Python_projects/Smartest/media/video.py#L78)

### Чого Все Ще Бракує Відносно Цілі

- provider separation by capability is only partial;
- `OPENAI_BASE_URL`/provider abstraction is not wired through;
- search has no explicit evaluator layer and no human-quality synthesis contract beyond the model loop;
- Telegram "geometry" is only partially implemented through reply/mention handling, not as a full normalized graph of context;
- control plane/dashboard is absent;
- legacy and new runtime are not yet converged into one deployable system.

## Рекомендовані Наступні Кроки

### 1. Прийняти Жорстке Рішення По Рантайму

Вибір:

- або `run.py` стає канонічною лінією;
- або команда свідомо лишається на `main.py`.

Моя оцінка:

- канонічною повинна стати `run.py`-лінія;
- `main.py`/`src/*` слід вважати legacy.

### 2. Стабілізаційний Спринт Перед Роботою Над Фічами

Перший практичний sprint має бути не про нові фічі, а про:

- один entrypoint;
- один env contract;
- один deploy path;
- один test path;
- one-pass cleanup merge corruption in `agent`, `media`, `requirements`.

### 3. Заморозити Legacy-Шар

Поки не прийнято рішення про перенос корисних шматків:

- не розвивати `src/*`;
- не додавати нові фічі в `main.py`;
- не синхронізувати дві архітектури вручну.

### 4. Після Стабілізації Перейти До Розділення За Можливостями

Лише після стабілізації runtime є сенс йти в:

- provider split;
- explicit planner/evaluator;
- search iterations;
- richer media semantics;
- control plane.
