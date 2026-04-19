# План переходу Smartest у мультикористувацький режим

**Статус:** частково реалізовано (Stages 1-4 done, Stage 4.5A done; §12.3 Частини А-Б виконані, pricing seed + Gemini usage fix закриті, keypool-first policy для billed turns виконана, `/balance` breakdown закритий, voice/persona в Telegram `/settings` закриті, thread-safe `_maybe_emit_billing` + revolver E2E пройдені на свіжому стенді 2026-04-19; активний спринт — portal/login і Stage 7 deploy)
**Дата створення:** 2026-04-17
**Аудит:** 2026-04-18

### Статус по етапах (коротко)

| Етап | Статус | Критичні gaps |
|------|--------|---------------|
| 1 — DB schema | ✅ | — |
| 2 — Key pool + Gateway | ⚠️ | runtime вже бере ключі з keypool пріоритетно для billed turns, `pricing` автосіється під час bootstrap, Gemini usage extraction виправлений, `_maybe_emit_billing` тепер працює і з worker threads (sync `chat_once` через `asyncio.to_thread`), revolver під 429 пройдений E2E; незакритий хвіст тут уже не policy, а операційне засівання `provider_keys` у проді, щоб env-fallback майже не використовувався |
| 3 — Policy + debit | ✅ | — |
| 4 — Telegram UI | ✅ | `/settings` уміє вибір моделі/провайдера для 3 груп, окремі `voice` і `persona`, а `/balance` уже показує breakdown через `/balance last` і `/balance turn <id>` |
| 4.5A — Admin dashboard | ✅ | базовий multitenant admin dashboard закрито: `/admin/users`, деталка, ручне поповнення, `/admin/transactions`, `/admin/chats`, `/admin/topups`, `/admin/keys` |
| 4.5B — User portal + TG Login | ❌ | не розпочато |
| 5 — Monobank | ❌ | відкладено свідомо |
| 6 — ToS/Privacy | ❌ | — |
| 7 — Бета | ❌ | — |

### Що блокує деплой

1. **Найгрубіше блокування event loop уже знято, і execution environment доведений до нового path на базовому рівні** — sync LLM-виклики з async-контуру переведені на безпечний bridge, `DB_POOL_SIZE` піднято до 50, а в `run.py` з'явився явний default executor на 128 worker-ів. Наступний performance-крок тепер не в bridge/sizing, а в acceptance під реальним навантаженням і за потреби подальшому tuning.
2. **Економіка Stage 2 уже не нульова і policy-level path для billed turns теж закритий, але лишається operational хвіст** — `pricing` сіється автоматично під час `bootstrap_db()`, Gemini usage extraction уже рахує thought tokens, а billed turn тепер пріоритезує keypool. Незакритим лишається вже не кодовий борг, а операційна задача: засіяти `provider_keys`, щоб env-fallback майже не використовувався.
3. **Telegram `/settings` ще не закриває весь персональний профіль** — моделі вже обираються, але голос і persona ще не винесені в TG UI, а media-group ще не включає TTS як повноцінну частину вибору.
4. **Прозорий breakdown у `/balance` уже є як базовий user-facing інструмент** — `/balance last` і `/balance turn <id>` показують sub-транзакції по planner/search/final з провайдером, моделлю, usage counters і вартістю. Незакритий хвіст у цьому напрямі тепер не сам breakdown, а можливе майбутнє розширення веб-історії до такого самого рівня деталізації.
5. **Admin dashboard закритий як базовий Stage 4.5A, але це не означає, що portal/login треба робити вже зараз** — після аудиту пріоритет зсунувся: спочатку треба стабілізувати runtime і білінг, і лише потім переходити до Stage 4.5B.
**Контекст:** проєкт наразі — повноцінний Telegram-бот з багаторічною історією, який щоденно використовується в одному чаті. Наступний крок — зробити його масовим продуктом, який можна відкрити для широкого загалу, з оплатою та ізольованими налаштуваннями під кожного користувача/чат.

### Поточний робочий порядок після аудиту 2026-04-18

Аудит у `§12` змінив порядок робіт. До нього природно виглядало, що після закриття Stage 4.5A треба йти або в user portal, або в polishing Telegram/UI-хвостів. Після аудиту це вже неправильний порядок, бо найбільший ризик не в тому, що десь бракує сторінки чи кнопки, а в тому, що сам runtime ще не готовий до реального multitenant-навантаження і може одночасно давати нульові списання.

Станом на **2026-04-19** перший runtime-крок уже закрито: sync `chat_once` більше не блокує async execution path напряму. Це не означає, що performance-пакет завершений повністю; це означає, що ми зняли найгрубіший bottleneck і тепер переходимо до Частини Б та економічних фіксів.

Тому далі план такий.

1. **✅ Частина А з `§12.3` виконана.** Прямі sync-виклики `chat_once` прибрані з async execution path через безпечний bridge, а concurrency-regression доданий. Найгрубіше серіалізування запитів на рівні event loop зняте.

2. **✅ Пропускну здатність середовища доведено до нового execution path на рівні Part B з `§12.3`.** `DB_POOL_SIZE` тепер має production-default 50, у `run.py` заведений явний `ThreadPoolExecutor(max_workers=128)`, а staging/full pytest пройдено вже на цьому конфігу. Це закриває другу половину того самого performance-фіксу і дозволяє рухатися далі в billing correctness.

3. **✅ Базову економіку вже закрито на рівні correctness.** `pricing` таблиця більше не лишається порожньою: missing rows автоматично вставляються під час `bootstrap_db()`, окремий seed-скрипт більше не робить подвійний прохід, а staging/live уже підтвердили, що таблиця реально заповнюється. Gemini usage extraction теж виправлений: токени для `usageMetadata` тепер включають `candidatesTokenCount` і `thoughtsTokenCount`, тому reasoning-виклики Gemini більше не падають у `0 / 0` і не дають нульову ціну лише через transport wrapper.

4. **✅ Runtime уже переведено в keypool-first режим для billed turns.** `resolve_provider_binding` тепер на повному billing-turn спочатку бере ключ із keypool, а env-шлях лишається лише контрольованим fallback з окремим `key_source='env_fallback'` і warning-логом. Це знімає головну проблему тихої втрати `key_id` attribution. Наступний крок тут уже не policy, а засіяти `provider_keys` і зменшити частоту самого fallback.

5. **Тільки коли performance і billing чесні, повертаємось до користувацьких хвостів Stage 4.** Breakdown у `/balance` уже закритий, тому далі тут лишаються voice/persona в `/settings` і TTS як частина media-group. Це важливі фічі, але вони не мають випереджати фундаментальні блокери runtime й економіки.

6. **Stage 4.5B з portal/login тепер свідомо відсунений після цього пакета.** Не тому, що він не потрібен, а тому, що user portal над заблокованим event loop і сирим billing-контуром лише швидше винесе назовні проблеми, які треба було закрити на рівні ядра.

---

## 1. Мотивація

Smartest уже має багате ядро: планувальник, мульти-провайдерна архітектура, трьохшарова пам'ять, голос, vision, пошук, адмін-панель. Усе це зараз обслуговує єдиний екземпляр одного власника (тебе). Якщо відкрити доступ зовнішнім користувачам у поточному стані, будуть три критичні проблеми:

1. **Усі користуються твоїми API-ключами без обмежень** — хтось у групі почне масово запускати search/video, і рахунок OpenAI/Gemini вибухне за добу.
2. **Налаштування глобальні по чату** — персона, модель, голос налаштовуються один раз для всіх. Якщо Олена хоче дешеву модель, а Петро — Opus 4.7, один із них буде страждати.
3. **Ніякої ідентифікації та контролю доступу** — будь-хто, хто опинився в групі, автоматично стає користувачем. Немає бану, немає лімітів, немає whitelist.

Мета рефакторингу — перетворити існуючий бот на продукт, де:
- Кожен користувач має власний акаунт із pre-paid балансом у гривнях.
- Кожен чат має власника (того, хто платить), який керує доступом і лімітами.
- Провайдерські ключі залишаються на нашій стороні, але розподілені через пул із балансуванням навантаження.
- Усі важливі налаштування доступні через Telegram (`/settings`, `/balance`, `/topup`); веб-панель залишається як advanced-інтерфейс для детального контролю та історії.

Технічно продукт залишається тим самим. Ми не переписуємо ядро, ми додаємо навколо нього три нові шари: **ідентифікація**, **облік/оплата**, **політика доступу**.

---

## 2. Поточний стан vs цільовий стан

| Область | Зараз | Після рефакторингу |
|---------|-------|-------------------|
| Ідентифікація | Немає. `chat_id` — єдиний identifier. Telegram `user_id` використовується для логів, але не для дозволів. | `users` таблиця з `tg_user_id`. Кожне повідомлення атрибутується конкретному акаунту. |
| Акаунти | Немає. Усі користуються твоєю конфігурацією. | `accounts` таблиця. Один акаунт = одна людина = один баланс, може бути власником багатьох чатів. |
| Оплата | Немає. Твої ключі, твій рахунок у провайдерів. | Pre-paid баланс у гривнях. Поповнення через monobank acquiring. Списання за фактом використання токенів. |
| Провайдерські ключі | Один ключ на провайдера в `.env`. | Пул (5-10 ключів на провайдера) з balancing по rate-limits і помилках. |
| Облік витрат | Немає (тільки логи). | `transactions` таблиця. Кожен LLM-виклик = окрема транзакція з `turn_id` для групування. Юзер бачить повний breakdown у `/balance`. |
| Налаштування | Per-chat у `settings` таблиці. Єдиний набір для всіх у чаті. | Per-user **і** per-chat з наслідуванням. Користувач задає персональні дефолти, чат може перевизначити. |
| Контроль доступу | Будь-хто в чаті автоматично користувач. | `chat_policies` + `chat_access`: режими `open`/`whitelist`/`admins_only`/`owner_only`, бан-ліст, per-user денні ліміти. |
| UI | Веб-адмінка на localhost. | Telegram `/settings`, `/balance`, `/topup`, `/allow`, `/ban`, `/mode`. Веб-панель розширена до повної історії транзакцій. |
| Масштаб | ~1 чат, ~5 юзерів активно. | Розрахунок на пару тисяч юзерів. Polling залишається, але архітектура готова до webhook-переходу. |
| Юридично | Немає. | ФОП 3 група, ToS/Privacy/Refund на сайті, реквізити у футері. |

---

## 3. Ключові архітектурні рішення

Ці рішення вже зафіксовані в обговоренні — доводимо їх до рівня документа, щоб не перевідкривати під час імплементації.

### 3.1. Pre-paid баланс, не post-paid

Користувач поповнює баланс (напр. 100 грн), сума вказана в гривнях. Перед кожним запитом система робить **preflight estimate** — оцінює вхідні токени + приблизну кількість вихідних (за capability) + націнку, перетворює в гривні. Якщо поточний баланс менший за estimate — запит блокується з повідомленням "поповни баланс".

Причина: post-paid відкриває на зловживання (вкрали Telegram → спалили чужий рахунок на тисячі гривень за ніч). Pre-paid обмежує збитки сумою, яку юзер сам клав.

### 3.2. Один власник на чат, з окремою оплатою

Коли бот додається в чат, першим платоспроможним користувачем, який звернувся до нього, стає **owner** цього чату. Owner:
- платить за всі запити в цьому чаті зі свого балансу;
- керує access policy (хто може писати);
- встановлює per-user і per-chat денні ліміти;
- може банити конкретних юзерів у межах чату;
- може делегувати частину прав TG-адмінам (наприклад, зміна persona, але не моделі).

У приватному чаті owner = єдиний юзер.

### 3.3. Повна прозорість витрат

Кожен sub-виклик (planner → search composer → evaluator → final synthesis → tts тощо) логується як **окрема транзакція** з полями `turn_id`, `capability`, `provider`, `model`, `tokens_in`, `tokens_out`, `cost_uah`. У UI `/balance` користувач бачить:

```
Повідомлення #1234 (сумарно: 0.18 грн)
  ├─ planner            → gpt-5.4-mini     → 500 in / 80 out   → 0.01 грн
  ├─ search composer    → gpt-5.4-mini     → 300 in / 40 out   → 0.005 грн
  ├─ web search API     → brave            → 1 query           → 0.002 грн
  ├─ search evaluator   → gpt-5.4-mini     → 200 in / 50 out   → 0.003 грн
  └─ final synthesis    → gemini-3.1-pro   → 2000 in / 600 out → 0.16 грн
```

Нічого не агрегуємо в "один рядок" — юзер має розуміти, куди йдуть його гроші. Агрегація — тільки візуальна (згортання дерева в UI).

### 3.4. Ключовий пул на нашій стороні

Користувачі **не приносять свої API-ключі**. Ми тримаємо 5-10 ключів на провайдера (5 OpenAI, 5 Gemini, 3 Anthropic через OpenRouter тощо), розподіляємо навантаження. Юзер обирає тільки провайдера і модель, за якою готовий витрачати. Націнка на тарифах провайдера (приблизно +30-50% до USD-ціни) покриває наш ризик і маржу.

### 3.5. Тільки українська аудиторія, тільки monobank

- Резиденти України, ФОП 3 група (5% єдиний податок з обігу).
- Еквайринг: monobank Invoice API (monopay) — найпростіший вхід, webhook-модель.
- Без міжнародних карт, без Stripe, без VAT MOSS.
- Про РФ/РБ не думаємо — не наша аудиторія.

### 3.6. Повна прозорість транзакцій, без тріалу

- Немає безкоштовного тріалу — запобігає масовому абузу через фейкові акаунти.
- Перший платіж — мінімум 50 грн (або інша сума, узгодимо при імплементації).
- Можливо — маленький welcome-bonus (5 грн) на демонстрацію функціоналу.

---

## 4. Схема бази даних

Це найважливіша частина — від схеми залежить усе інше. Нові таблиці нижче, існуючі (`settings`, `memory_*`, `chat_members`) залишаються, але отримують додаткові зв'язки.

```sql
-- Користувачі (один запис на Telegram user_id)
users (
  id               BIGINT PK AUTO_INCREMENT,
  tg_user_id       BIGINT UNIQUE NOT NULL,
  tg_username      VARCHAR(64),
  first_name       VARCHAR(128),
  first_seen_at    TIMESTAMP,
  last_seen_at     TIMESTAMP
)

-- Акаунти (біллінг-ідентичність, 1:1 з users на старті, але FK для гнучкості)
accounts (
  id               BIGINT PK AUTO_INCREMENT,
  owner_user_id    BIGINT FK → users.id,
  balance_uah      DECIMAL(12,4) DEFAULT 0,
  total_spent_uah  DECIMAL(12,4) DEFAULT 0,
  total_topup_uah  DECIMAL(12,4) DEFAULT 0,
  status           ENUM('active','frozen','deleted') DEFAULT 'active',
  created_at       TIMESTAMP
)

-- Чати (TG-чат з прив'язкою до акаунта-власника)
chats (
  id                BIGINT PK AUTO_INCREMENT,
  tg_chat_id        BIGINT UNIQUE NOT NULL,
  tg_chat_type      ENUM('private','group','supergroup','channel'),
  title             VARCHAR(256),
  owner_account_id  BIGINT FK → accounts.id,
  added_at          TIMESTAMP
)

-- Політики чату (налаштовує власник)
chat_policies (
  chat_id                   BIGINT PK FK → chats.id,
  access_mode               ENUM('open','whitelist','admins_only','owner_only') DEFAULT 'open',
  per_user_daily_cap_uah    DECIMAL(8,4) DEFAULT 5.0,
  per_chat_daily_cap_uah    DECIMAL(8,4) DEFAULT 50.0,
  alert_threshold_pct       TINYINT DEFAULT 80,
  updated_at                TIMESTAMP
)

-- Доступ окремих юзерів у чаті (whitelist / ban / delegated admin)
chat_access (
  id               BIGINT PK AUTO_INCREMENT,
  chat_id          BIGINT FK → chats.id,
  user_id          BIGINT FK → users.id,
  role             ENUM('allowed','banned','delegated_admin'),
  added_by         BIGINT FK → users.id,
  added_at         TIMESTAMP,
  UNIQUE (chat_id, user_id)
)

-- Налаштування на рівні користувача (персональні дефолти)
user_settings (
  user_id    BIGINT FK → users.id,
  key        VARCHAR(64),
  value      TEXT,
  PRIMARY KEY (user_id, key)
)

-- Turns — логічне повідомлення юзера (може згенерувати 1-10 транзакцій)
turns (
  id                UUID PK,
  account_id        BIGINT FK → accounts.id,
  chat_id           BIGINT FK → chats.id,
  user_id           BIGINT FK → users.id,
  tg_message_id     BIGINT,
  user_message_text TEXT,
  route             VARCHAR(32),
  capability        VARCHAR(64),
  total_cost_uah    DECIMAL(10,4),
  status            ENUM('running','completed','failed','budget_blocked'),
  created_at        TIMESTAMP,
  completed_at      TIMESTAMP
)

-- Транзакції — кожен LLM/API виклик окремо
transactions (
  id            BIGINT PK AUTO_INCREMENT,
  turn_id       UUID FK → turns.id,
  account_id    BIGINT FK → accounts.id,
  chat_id       BIGINT FK → chats.id,
  user_id       BIGINT FK → users.id,
  kind          ENUM('llm_call','search_api','tts','stt','fetch_page'),
  capability    VARCHAR(64),
  provider      VARCHAR(32),
  model         VARCHAR(64),
  tokens_in     INT DEFAULT 0,
  tokens_out    INT DEFAULT 0,
  unit_count    INT DEFAULT 0,           -- для search queries, tts chars тощо
  cost_usd      DECIMAL(10,6),
  cost_uah      DECIMAL(10,4),
  markup_pct    DECIMAL(5,2),
  key_id        BIGINT FK → provider_keys.id,
  latency_ms    INT,
  status        ENUM('success','failed','rate_limited'),
  created_at    TIMESTAMP,
  INDEX (account_id, created_at),
  INDEX (turn_id)
)

-- Ключовий пул
provider_keys (
  id              BIGINT PK AUTO_INCREMENT,
  provider        VARCHAR(32),
  key_hash        CHAR(64),               -- sha256 для логів без розкриття
  encrypted_key   TEXT,                   -- зашифрований AES-256
  label           VARCHAR(64),
  rpm_limit       INT,
  tpm_limit       INT,
  status          ENUM('active','disabled','rate_limited','invalid'),
  last_used_at    TIMESTAMP,
  last_error_at   TIMESTAMP,
  last_error      TEXT,
  total_spent_usd DECIMAL(12,4) DEFAULT 0
)

-- Поповнення (monopay invoices)
topups (
  id                  BIGINT PK AUTO_INCREMENT,
  account_id          BIGINT FK → accounts.id,
  amount_uah          DECIMAL(10,2),
  monopay_invoice_id  VARCHAR(64) UNIQUE,
  monopay_url         TEXT,
  status              ENUM('created','pending','success','expired','failed'),
  created_at          TIMESTAMP,
  paid_at             TIMESTAMP,
  webhook_payload     JSON
)

-- Прайс-лист (наші націнки на моделі)
pricing (
  id                      BIGINT PK AUTO_INCREMENT,
  provider                VARCHAR(32),
  model                   VARCHAR(64),
  input_usd_per_1m        DECIMAL(10,4),
  output_usd_per_1m       DECIMAL(10,4),
  markup_pct              DECIMAL(5,2) DEFAULT 40,
  uah_rate                DECIMAL(8,4),   -- UAH per USD на момент оновлення
  updated_at              TIMESTAMP,
  UNIQUE (provider, model)
)
```

**Важливе про транзакційність:** списання з балансу і створення транзакції — атомарна операція. Використовуємо `SELECT ... FOR UPDATE` на `accounts.balance_uah` у тій же транзакції, де INSERT у `transactions`.

---

## 5. Архітектура коду

Новий код збирається в окремий модуль `billing/`, щоб не розплескуватися по всій базі:

```
billing/
├── __init__.py
├── accounts.py       # CRUD акаунтів, атомарне списання/поповнення
├── gateway.py        # Обгортка навколо chat_once, логує транзакції
├── pricing.py        # Конвертація провайдерських цін → гривні з націнкою
├── policy.py         # Перевірка access_mode, per-user/per-chat caps, банів
├── monopay.py        # Створення інвойсу, обробка webhook
├── keypool.py        # Ротація ключів, rate-limit tracking
└── turns.py          # Створення turn_id, агрегація транзакцій
```

Основна точка інтеграції — `agent/llm.py::chat_once`. Наразі він приймає messages і повертає response. Після рефакторингу:

1. `app/message_logic.py` створює `turn_id` на початку обробки повідомлення.
2. Викликає `policy.check_access(chat, user)` — перевіряє режим доступу і бани.
3. Перед кожним LLM-викликом викликає `policy.check_budget(account, estimated_uah)` — перевіряє баланс і денні ліміти.
4. Сам виклик іде через `billing.gateway.chat_once(..., turn_id=X, user_id=Y, account_id=Z)`, який:
   - обирає ключ з пулу (`keypool.acquire(provider)`);
   - виконує запит;
   - отримує usage з response;
   - конвертує в гривні через `pricing.compute_cost(...)`;
   - атомарно списує з балансу і пише транзакцію;
   - повертає response як зараз.
5. У кінці turn — `turns.finalize(turn_id)`: підсумовує транзакції, оновлює `total_cost_uah`, `status`.

Це **єдине місце зміни** в бізнес-логіці бота. Усі existing callsites `chat_once(...)` переходять на `billing.gateway.chat_once(...)` з додатковим параметром `billing_context` (об'єкт із `turn_id`, `user_id`, `account_id`, `chat_id`).

Один важливий нюанс: `billing_context` має прокидатися через усі шари (planner, search_task, memory — всі вони теж викликають `chat_once`). Тобто функції на кшталт `plan_message`, `build_search_task`, `summarize_block` мають отримати новий параметр. Це найбільший рефакторинг у проєкті, але чистий — додається один параметр.

---

## 6. Етапи імплементації

Розбив на логічні порції роботи. Кожен етап — закінчена функціональність, яку можна протестувати і за потреби merge в master. У нашому режимі спільної роботи кожен — орієнтовно одна-дві повноцінні сесії.

### Етап 1. Схема БД + базові моделі ✅ Зроблено

**Що робимо.** Створюємо міграцію `006_multitenant.sql` з усіма таблицями з розділу 4. Пишемо репозиторії (`db/accounts_repository.py`, `db/chats_repository.py`, `db/transactions_repository.py`, `db/keypool_repository.py`, `db/topups_repository.py`, `db/users_repository.py`).

**Що зміниться для існуючого бота.** Нічого. Нові таблиці додаються, старі не чіпаються. Бот продовжує працювати так само, але тепер кожен чат є звичайним чатом в єдиній системі.

**Очікуваний результат.** Міграція застосовується без помилок на проді і стейджі. Унтест-репозиторії для CRUD операцій проходять. Можна вручну створити юзера/акаунт/чат через Python-консоль і побачити в БД.

### Етап 2. Ключовий пул і LLM gateway ⚠️ Частково

**Що зроблено:** `billing/gateway.py` логує транзакції через ContextVar BillingContext. `billing/keypool.py` підключений до runtime: `core/provider_registry.py` при активному billing turn спочатку пробує взяти ключ із `provider_keys`, кешує його в межах turn, а `agent/llm.py` / `billing/gateway.py` тепер зберігають `key_id` у транзакціях і відмічають success/rate-limit/auth-error на рівні key pool.

**Що НЕ зроблено (gaps):**
- `pricing` таблиця порожня — ціни не заповнені, fallback через hardcoded markup
- Ключі з `.env` ще НЕ перенесені масово в `provider_keys` — runtime вже вміє брати ключ із пулу, але для неseed-нутих провайдерів лишається `.env` fallback
- UI для керування key pool уже є (`/admin/keys`), тому seed / enable / disable / cooldown visibility більше не зав'язані на SQL вручну

**Що планувалось:** Переносимо ключі з `.env` у таблицю `provider_keys` (шифруємо AES-256 з майстер-ключем у `.env`). `billing/keypool.py` — вибір ключа за стратегією "найменше завантажений, не на cooldown". Оновлюємо `pricing` таблицю актуальними цінами станом на квітень 2026 з націнкою 40%.

На цьому етапі ще немає полісі, юзерів, балансу — просто **всі запити логуються в `transactions`** з прив'язкою до твого (єдиного) акаунта. Після етапу ти можеш відкрити БД і побачити, скільки кожен запит коштує в грн.

**Що зміниться для існуючого бота.** Усі callsites `chat_once` мігрують на `billing.gateway.chat_once`. Прокидаємо `billing_context` через planner, search_task, memory. Бот поводиться так само, але тепер кожен LLM-виклик має запис у `transactions`.

**Очікуваний результат.** Після реального використання бота протягом дня — у БД є кілька сотень транзакцій з коректними витратами. Можна зробити SQL-запит "скільки я витратив за сьогодні на search vs chat" і побачити реальні числа. Rate-limit errors автоматично виводять ключ у cooldown.

### Етап 3. Біллінг-логіка і політика доступу ✅ Зроблено

**Що робимо.** Пишемо `billing/accounts.py` з атомарним списанням. `billing/policy.py` — перевірка access_mode, per-user/per-chat денних лімітів (денні ліміти рахуються як sum транзакцій за добу). Інтегруємо в `app/message_logic.py`: на початку обробки — перевірка policy, потім preflight check балансу, потім виконання, потім фіналізація turn.

У конфігурації чату створюємо `chat_policies` запис при першому повідомленні. Власником автоматично стає перший юзер з балансом > 0, який написав.

**Що зміниться для існуючого бота.** З'являється реальна перевірка доступу. У групі, куди додали бота, але немає owner'a з балансом — бот мовчить (або ввічливо каже "мене ще не активували"). Після призначення owner'а і поповнення балансу — працює як зазвичай, але з лімітами.

**Очікуваний результат.** Якщо баланс акаунта-власника > 0 — бот працює. Якщо виставити баланс 0 — бот пише "поповни баланс". Якщо виставити per_user_daily_cap 5 грн — після вичерпання бот мовчки ігнорує юзера до наступного дня. Твій акаунт не відрізняється від будь-якого іншого, просто баланс великий.

### Етап 4. Telegram UI — /settings, /balance, /topup, /allow, /ban, /mode ⚠️ Частково

**Зроблено:** `/start`, `/balance`, `/topup`, `/mode`, `/allow`, `/ban`, `/unban`, `/cap`, `/settings` і окрема `/model`. Команди диспатчаться до legacy access gate. Для персональних моделей зʼявився inline-flow: `/model` і `/settings` відкривають меню з трьома групами (`chat`, `think`, `media`), вибір зберігається в `user_settings`, а runtime читає його через `BillingContext.meta` перед `.env`. Для Telegram callback-и обробляються окремим PTB handler-ом, без падіння в звичайний message flow.

**Що реально працює після виправлення:**

- `/settings` показує не лише policy, а й персональні моделі;
- є inline-клавіатури: група → провайдер → модель;
- провайдери показуються тільки якщо для них реально є API-ключ у `.env` або в `provider_keys`;
- вибір користувача застосовується до `chat_final`, `planner_reasoning` + `memory_summary`, `vision_image`;
- gateway і загальний provider binding беруть ці user overrides перед server default.

**НЕ зроблено (критичні gaps, які ще лишаються):**

- **Voice/persona в Telegram UI вже закриті.** `billing/commands.py` тепер показує окремі inline-меню для голосу озвучки і persona, а вибір зберігається в `user_settings`.
- **Runtime їх реально читає.** `media/voice.py` бере `voice_id` з `BillingContext.meta["user_settings"]`, а `core/prompts.py` підмішує `persona_slug` у системний persona-layer перед фінальною відповіддю і search synthesis.
- **Веб-адмінка Stage 4.5A вже закрита як базовий multitenant dashboard.** Працюють `/admin/users`, `/admin/users/<id>`, `/admin/users/<id>/credit`, `/admin/transactions`, `/admin/chats`, `/admin/topups` і `/admin/keys`.

**Вибір моделей у Telegram (тепер реалізований як baseline):**
- 💬 **Відповідь** (`chat_final`) — головна модель, найбільша частка витрат;
- 🧠 **Думалка** (`planner_reasoning` + `memory_summary`) — дешевший reasoning/runtime шар;
- 🎙 **Медіа** (`vision_image`) — мультимодальний baseline для аналізу медіа;
- Пошук (`search_*`) навмисно не віддається юзеру, це глобальна операційна політика;
- На веб-порталі пізніше буде повний per-capability вибір, але базовий user-facing control для voice/persona вже є в Telegram.

**Де зберігається:** `user_settings(user_id, key, value)` — ключі `chat_provider`, `chat_model`, `think_provider`, `think_model`, `media_provider`, `media_model`. У runtime вони завантажуються в `BillingContext.meta["user_settings"]`, а далі читаються в `core/provider_registry.py`.

**Очікуваний результат у поточному стані.** Юзер пише `/model` або `/settings` → бачить inline-клавіатуру → обирає "Відповідь" → "Gemini" → `gemini-2.5-pro` → бот підтверджує → наступні запити цієї людини йдуть через `gemini-2.5-pro` для `chat_final`, не зачіпаючи інших учасників чату.

### Етап 4.5. Web Portal — Admin Dashboard + User Portal + Telegram Login

> Детальна архітектура: `docs/project/portal-architecture.md`

**Контекст.** Telegram у квітні 2026 релізнув новий Login Widget — авторизація + запит телефону + permission to message в одному попапі, безкоштовно, без OIDC-провайдерів. JWT верифікується через публічні ключі `oauth.telegram.org/.well-known/jwks.json`.

**Stage 4.5A — Admin dashboard (пріоритет, без нового login):**

Нові сторінки в існуючому admin_ui (BaseHTTPRequestHandler):
- `/admin/users` — таблиця юзерів з сортуванням: username, first_seen, last_seen, balance, total_spent, запитів всього/сьогодні/7д, токени, улюблена модель. Дія: [Деталі]
- `/admin/users/<id>` — детальна картка: профіль, owned chats, recent turns, recent transactions, recent topups, user_settings
- `/admin/users/<id>/credit` — ручне поповнення з сумою і обов'язковою нотаткою. Працює як тимчасовий Stage 4.5A механізм до Monobank
- `/admin/transactions` — global лог з фільтрами (user, capability, provider, model, дата)
- `/admin/chats` — таблиця чатів: owner, access_mode, ліміти, денна/загальна витрата
- `/admin/topups` — всі поповнення (admin_manual + monopay)
- `/admin/keys` — пул провайдерських ключів: додати, enable/disable, переглянути stats (spent_usd, last_error, cooldown). Ключ зберігається зашифрованим (AES-256-GCM через існуючий `billing/crypto.py`)

Поточний стан Stage 4.5A:
- **Вже зроблено:** `list_users_with_stats`, `get_user_admin_detail`, `credit_account_admin`, сторінки `/admin/users` і `/admin/users/<id>`, POST `/admin/users/<id>/credit`, сторінки `/admin/transactions`, `/admin/chats`, `/admin/topups`, `/admin/keys`, базові регресійні тести, інтеграція в існуючий `admin_ui`.
- **Що лишається поза Stage 4.5A:** більш глибокі admin-аналітики на кшталт breakdown по capability на окремій сторінці користувача, user portal і Telegram Login.

**Stage 4.5B — Telegram Login + User Portal:**

- `@BotFather` → `/setdomain smartest.klawa.top` (вручну)
- Backend: `verify_telegram_token(id_token, bot_id)` через `python-jose[cryptography]`
- `/auth/telegram` POST endpoint
- User portal: `/` (dashboard), `/history`, `/history/<turn_id>` (turn breakdown), `/topup`, `/settings`
- Admin perms: `ADMIN_TG_USER_IDS` в `.env` — список числових tg_user_id
- Admin backdoor: `[HIDDEN_SUBDOMAIN].smartest.klawa.top` → password login (існуючий механізм), URL не публікується, тільки в `.env`
- Caddy: два server blocks — основний + backdoor subdomain

**Що зміниться для існуючого бота.** Адмін отримує повний dashboard з реальними даними. Юзери отримують веб-портал де видно баланс, витрати і историю без Telegram. Додавання API ключів провайдерів — через UI замість ручного `.env`.

**Очікуваний результат.** Ти заходиш на `smartest.klawa.top` через свій Telegram-акаунт → бачиш `/admin` з таблицею юзерів → можеш вручну поповнити баланс будь-кому → додати/вимкнути провайдерський ключ. Юзер заходить на `smartest.klawa.top` → бачить баланс і витрати.

### Етап 5. Monobank інтеграція

**Важливо:** До Етапу 5 інклюзивно оплата — НЕ імплементується. На етапах 1-4.5 баланси юзерів встановлюються вручну:
- Через `/admin/users/<id>/credit` в веб-адмінці → форма з сумою + нотаткою
- Або напряму в БД SQL-запитом (для швидкого тестування)

Це дозволяє тобі приготувати усе, потестити з реальними людьми на пісочниці, і тільки **потім** додати реальну оплату.

---

**Що робимо** (коли дійдемо до етапу). Реєстрація merchant-акаунта в monobank (це ти робиш вручну, я допомагаю з інтеграцією). Пишемо `billing/monopay.py` — виклик Invoice API для створення рахунку, webhook-endpoint на нашій стороні (вже є HTTP сервер в admin_ui, додаємо `/webhook/monopay`). Після отримання webhook-у з `status=success` — додаємо суму до `accounts.balance_uah`, оновлюємо `topups.status`.

**Що зміниться для існуючого бота.** `/topup` стає функціональним — генерує реальне посилання на оплату. Після успішної оплати — Telegram-повідомлення юзеру "Баланс поповнено на 100 грн, поточний: 100 грн".

**Очікуваний результат.** Ти робиш тестовий платіж на 10 грн через свою картку, отримуєш повідомлення, бачиш оновлений баланс. Webhook signature перевіряється, fake webhook відкидається.

### Етап 6. Юридична обгортка

**Що робимо.** Дві сторінки на сайті (наш же HTTP-сервер): `/terms`, `/privacy`, `/refund`. Тексти генеруємо з темплейтів для UA IT-SaaS (можу прогнати через Claude для генерації першого варіанту, потім юрист валідує). Реквізити ФОП у футері (ФОП, ПІБ, код ЄДРПОУ, e-mail). Посилання на ці сторінки — у `/start` і в `/settings` → "Про сервіс".

**Що зміниться для існуючого бота.** Перша взаємодія з новим юзером показує "Натиснувши /accept, ви погоджуєтесь з умовами: [посилання]". Поки не акцепт — бот не обробляє повідомлень.

**Очікуваний результат.** Легально чисто. Якщо хтось поскаржиться — є формальні документи.

### Етап 7. Відкрита бета і моніторинг

**Що робимо.** Запрошуємо 20-50 людей (друзі, спільнота). Спостерігаємо за:
- Реальним розкидом витрат (хто скільки витрачає, які capability популярні).
- Патернами абузу (чи хтось пробує спамити, обійти ліміти).
- Проблемами з UI (що незрозуміло, де загубилися).
- Коректністю біллінгу (чи співпадають наші списання з реальним cost у провайдерів).

**Що зміниться для існуючого бота.** Перші реальні юзери крім тебе. Ти — customer support через @контакт.

**Очікуваний результат.** Протягом 2-4 тижнів ловимо основні баги і edge-cases. Після стабілізації — відкриваємо широко (чи там, де будемо рекламувати).

---

## 7. Що лишається без змін

Важливо не зламати те, що добре працює:

- **Ядро планувальника, пошуку, відео, vision** — жодних змін у логіці, тільки додавання `billing_context` у сигнатури функцій.
- **Триьшарова пам'ять** (recent + long + core) — залишається per-chat_id. Це принципово: пам'ять належить чату, а не юзеру. Якщо в групі 5 людей, бот пам'ятає загальний контекст чату, а не окремі фрагменти на кожного.
- **Адмін-панель як advanced-інтерфейс** — залишається, але розширюється.
- **Модель prompting** (capability prompts, persona) — залишається як є. Додається можливість per-user/per-chat override через налаштування.
- **Polling через PTB** — залишається. Webhook-міграція — окрема тема на потім, якщо дійсно будуть тисячі юзерів.
- **Deployment** (PM2 на Hetzner VPS) — залишається.

---

## 8. Відкриті питання, які вирішуватимемо по ходу

Це нетривіальні рішення, які не хочу замикати наперед, бо можуть змінитися під час реалізації:

1. **Як саме рахувати preflight estimate?** Точне — дорого (треба токенізувати вхід через tiktoken для кожного провайдера). Наближене — беремо `len(text) / 3.5` як токени, додаємо середній вихід по capability. Думаю, стартуємо з наближеного + резерв 20%.
2. **Що робити з існуючою пам'яттю?** При першому старті після міграції — seed-скрипт прив'язує всі існуючі `chat_id` з `settings` до відповідних акаунтів. Пам'ять (`memory_recent`, `memory_long`, `memory_core`) залишається per-chat_id, нічого не губиться.
3. **Шифрування провайдерських ключів у БД** — майстер-ключ в `.env`, ключі в БД зашифровані AES-256-GCM. Якщо master зламають — все одно треба БД. Прийнятний рівень.
4. **Per-user чи per-(user, chat) settings?** Я схиляюся до per-user з override per-chat. Тобто: "Моя дефолтна модель — GPT-5.4 Sonnet. У чаті XXX — Gemini 3.1 Pro". Це складніше в UI, але гнучкіше. Обговоримо коли дійдемо до /settings.
5. **Чи підтримуємо зміну власника чату?** Якщо оригінальний owner видалився/забанив бота — чат переходить наступному за хронологією учаснику з балансом? Або заморожується? Думаю, заморожується, власник викликає `/claim` і платить заново.
6. **Референс-програма для онбордингу** — напр. запроси друга, отримай 10 грн на баланс. Гарно для росту, але ризик абузу (фейкові акаунти). Вирішимо після бети.

---

## 9. Критерії успіху

Рефакторинг вважається завершеним, коли:

1. Міграція 004 застосована на проді, дані збереглися.
2. Усі існуючі чати продовжують працювати так само — власник кожного чату автоматично визначений при міграції, баланс твого акаунта великий, нічого не змінилось з точки зору використання.
3. Можна створити новий чат з новим юзером, поповнити баланс, писати боту — баланс списується коректно.
4. Усі запити логуються в `transactions` з прив'язкою до turn_id.
5. Команда `/balance` показує повну історію з breakdown по sub-викликах.
6. Політики (`access_mode`, `daily_cap`, `ban`) реально працюють — перевіряється ручним тестом.
7. Monobank інтеграція — реальний платіж з реальної картки поповнює реальний баланс.
8. ToS/Privacy доступні на сайті.
9. 20+ бета-юзерів протягом місяця без критичних інцидентів (втрата грошей, зависання, витік даних).

---

## 10. Ризики

Те, що може піти не так:

- **Race conditions на балансі.** Юзер одночасно надсилає 3 повідомлення, кожне бачить балансу достатньо, всі списуються, баланс стає від'ємним. Мітигація: `SELECT FOR UPDATE` на account row, черга per-account.
- **Cost drift.** Наша націнка може не покривати реальні витрати на якихось моделях (наприклад, якщо Gemini підвищить ціну). Потрібен моніторинг `SUM(transactions.cost_usd)` vs фактичний білл у провайдерів щомісяця.
- **Дзеркало monobank webhook'у.** Якщо webhook загубиться (наш сервер був у даунтайм), юзер оплатить, а баланс не поповниться. Мітигація: job, що періодично опитує `/invoice/status` для всіх `topups.status=pending`.
- **Заморожені ключі провайдерів.** Якщо OpenAI заблокує ключ (підозра в абузі), у пулі стає на одного менше. Мітигація: моніторинг + алерти, запас ключів.
- **Складність для користувача.** Забагато команд, забагато налаштувань. Дефолти мають бути "просто працює з коробки". Preset-и типу "Економ" / "Баланс" / "Максимум" в `/settings`.

---

## 11. Наступні кроки

Після узгодження цього документу — починаємо з Етапу 1 (міграція БД). Це найфундаментальніша річ, від неї залежить усе. Після цього кожен наступний етап логічно нарощується.

Кожен етап завершуємо commit'ом у гілку `multitenant` і підсумком у devlog. Merge у master тільки після того, як весь ланцюг працює end-to-end (тобто після Етапу 5 або 6).

---

## 12. Технічний аудит 2026-04-18 (Opus 4.7)

Цей розділ — підсумок ретельного аудиту після того, як над гілкою `multitenant` попрацювала інша модель. Пишу не економлячи символів, щоб наступна модель могла одразу взяти цей документ і піти фіксити, не читаючи заново весь код. Аудит покриває три питання: (а) що реально реалізовано добре, (б) які косяки знайшов, (в) критичний сценарій "а чи витримає воно сотню паралельних запитів".

### 12.1. Що зроблено добре

**Stage 4.5A — адмін-дашборд — закритий.**
- `db/admin_repository.py` (867 рядків) має повний CRUD-агрегатор: `list_users_with_stats`, `list_transactions_with_stats`, `list_chats_with_stats`, `list_topups_with_stats`, `list_provider_keys_with_stats`, плюс `get_*_summary` для totalів, плюс `get_user_admin_detail(user_id)` і `credit_account_admin`. Усі сортування проходять через `normalize_*_sort` помічники — серверний ORDER BY безпечний до SQL-ін'єкцій (whitelist колонок).
- `app/admin_ui.py` виріс до ~3635 рядків. Додані роути: `/admin/users`, `/admin/users/<id>`, `/admin/users/<id>/credit`, `/admin/transactions`, `/admin/chats`, `/admin/topups`, `/admin/keys`, `/admin/keys/add`, `/admin/keys/<id>/toggle`. Є спільний shell через `_admin_shell` і path parsers (`_parse_admin_user_detail_path`, `_parse_admin_user_credit_path`, `_parse_admin_key_toggle_path`).
- Закрита вимога "додавати/віднімати баланс юзеру" — `POST /admin/users/<id>/credit` → `credit_account_admin`.
- Seed / enable / disable / audit провайдерських ключів тепер повністю через UI, не потребує ручного SQL.

**Вибір моделі в Telegram — закритий.**
- `core/model_preferences.py` (85 рядків) визначає 3 групи (chat / think / media) з мапою `provider_slug → (model_slug, ...)`. Помічники: `group_for_capability`, `group_by_slug`, `provider_models`.
- `billing/commands.py` (869 рядків) має команду `/model` з inline-клавіатурами. Callback handler `_handle_model_callback` підтримує дії `root / group / provider / select / reset`. Render-функції: `_render_model_root`, `_render_group_menu`, `_render_provider_menu`, `_set_group_choice`.
- `_provider_available()` перевіряє і env, і `provider_keys` — юзер бачить тільки провайдерів, де адмін реально має ключ.
- `/settings` показує поточні вибори по групах. Selection зберігається в `user_settings(user_id, key, value)` під ключами `chat_provider`/`chat_model`/`think_provider`/`think_model`/`media_provider`/`media_model`.
- `core/provider_registry.py::resolve_provider_binding` читає цей override з `BillingContext.meta['user_settings']`, валідує що модель у whitelist провайдера (якщо ні — скидає назад до capability default).

**Keypool під'єднаний до runtime.**
- `billing/gateway.py::log_llm_transaction` тепер викликає `billing.keypool.record_success(key_id, cost_usd)`, `record_rate_limit(key_id)`, `record_error(key_id, error_text, disable=_is_auth_error(...))`. Тобто rotation і cooldown реально працюють.
- `_is_rate_limit_error` (шукає "rate limit", "429", "resource exhausted") і `_is_auth_error` (шукає "api_key_invalid", "unauthorized", "401", "403") — коректно класифікують помилки.
- `resolve_provider_binding` кешує binding на весь turn через `meta.setdefault("_provider_key_cache", {})` — один turn не буде витягати з pool дві різні зміни ключа на той самий провайдер.

**Тести 087-093 додані.** `test_087_user_model_binding`, `test_088_admin_repository`, `test_089_admin_dashboard`, `test_090_admin_transactions`, `test_091_admin_chats`, `test_092_admin_topups`, `test_093_admin_keys` — повністю окремі тестові контексти, моки DB, перевірка сортування і фільтрації.

### 12.2. Проблеми, знайдені в реалізації multitenant

**P1. `_run_async_sync` спавнить потік на кожен LLM-виклик** (`core/provider_registry.py:68-87`).

Код такий: якщо є running loop, спавнимо daemon thread, у ньому робимо `asyncio.run(coro)`, блокуємося на `thread.join()`. Використовується в `_cached_keypool_binding` для виклику `await billing.keypool.acquire(provider)`.

Чому це проблема: `resolve_provider_binding` викликається перед кожним LLM-запитом (з `chat_once`, `chat_once_billed`, і з `billing.gateway._maybe_emit_billing`). На гарячому шляху ми створюємо і знищуємо потік. Навіть з кешуванням у meta це спрацьовує як мінімум раз на capability-провайдера за turn. Плюс — coroutine `keypool.acquire` сам усередині робить `SELECT ... FOR UPDATE` — тобто ми зі свого event loop запускаємо інший event loop, який ходить у той самий DB pool. Це не deadlock поки що, бо потік окремий, але дуже крихко.

**Як правильно:** зробити `resolve_provider_binding` async і викликати з awaiting callsite. Або виносити acquire у `begin_turn` — щоб ключ вибирався один раз на весь turn і клався в `BillingContext.meta` ще до першого LLM-виклику. Тоді `resolve_provider_binding` читатиме з meta синхронно, без потоків.

**P2. Повний per-capability TTS binding ще не зроблений** (`core/model_preferences.py:56`).

User-facing хвіст Stage 4 уже закритий: Telegram `/settings` дає персональний `voice_id`, а `media/voice.py` реально його використовує під час озвучки. Але це ще не те саме, що повний model/provider binding для окремого `tts_synthesis` capability.

**Що лишається технічно:** якщо ми захочемо керувати не лише голосом, а й самим TTS-провайдером/моделлю на рівні multitenant runtime, треба буде завести окремий `tts_*` capability, включити його в catalog/group mapping і дати `provider_registry` той самий override-path, який уже працює для `chat_final`, `planner_reasoning` і `vision_image`.

**P3. Voice і Persona взагалі не в `/settings`.**

Зараз `/settings` показує тільки вибір моделі по трьох групах і chat policy block. Але Plan Stage 4 говорить прямо: *"Провайдер, Модель, **Голос**, **Persona**"*. Голос (який TTS-голос озвучує відповіді) і persona (який system prompt) — досі не виведені в UI.

**Статус на 2026-04-19:** закрито як baseline. У Telegram `/settings` і `/model` є окремі inline-меню для `voice_id` і `persona_slug`, значення зберігаються в `user_settings`, `media/voice.py` використовує `voice_id`, а `core/prompts.py::resolve_persona_for_user()` підмішує persona override в runtime prompt-layer.

**P4. `/balance` досі не має sub-transaction breakdown** (`billing/commands.py:578`).

Рядок 578 буквально каже: `"Детальний breakdown по sub-транзакціях ще окремим блоком допиляємо у Stage 4."`. Тобто досі тільки агрегована сума. А в плані Section 3.3 описана вимога показати кожну sub-транзакцію турну окремо (planner call, search call, media analysis, final chat call) з провайдером/моделлю/токенами/коштом.

**Як фіксити:** додати в `/balance` опцію `/balance last` (покаже останній turn розгорнуто) і `/balance turn <id>`. Зробити SQL: `SELECT * FROM transactions WHERE turn_id = ? ORDER BY created_at` і відрендерити таблицею. Для overview — групувати останні 20 turns по `turn_id`, показати загальну суму на turn і при тапі "показати деталі" розгорнути.

**P5. Хардкод списків моделей у `core/model_preferences.py`.**

`providers={"openai": ("gpt-5.4-mini", "gpt-5.4", ...), "anthropic": (...), ...}` — це статичний dict у коді. Коли адмін додасть нового провайдера чи нову модель через `/admin/keys`, модель не з'явиться у виборі в Telegram. Треба правити Python-код.

**Як фіксити:** або тягти `providers` з БД (нова таблиця `provider_catalog(provider_slug, model_slug, kind)` + seed), або тримати список у `pricing` таблиці (вона і так має `provider + model`), читати DISTINCT. Для MVP можна залишити хардкод, але тоді прибрати з плану пункт "юзер бачить тільки моделі, де є ключ" — бо моделі hardcoded і не знають нічого про реальний pool.

**P6. Пріоритет ключів у `resolve_provider_binding` був неправильний для продакшну. Статус: ✅ виконано 2026-04-19.**

Проблема була в тому, що billed turns могли тихо піти через `.env`, навіть якщо runtime уже вмів брати ключ із `provider_keys`. Це вбивало атрибуцію ключа (`key_id=None`) і робило admin/statistics неточними.

Це вже виправлено: якщо `billing_context.is_complete()`, runtime спочатку пробує keypool, а env використовується лише як контрольований fallback. Такі випадки тепер маркуються окремим `key_source='env_fallback'` і логуються як `provider_registry.env_fallback_used`, щоб операційно було видно, де пул ще не засіяний.

**P7. `pricing` таблиця була порожньою. Статус: ✅ виконано 2026-04-19.**

Проблема була в тому, що без seed `compute_cost_uah(...)` повертав нульову суму, транзакції логувалися як `0 UAH`, а preflight estimate брехав. Це вже закрито: під час `bootstrap_db()` тепер автоматично викликається `seed_pricing_defaults()`, у runtime і live БД missing rows більше не лишаються порожніми, а окремий `scripts/seed_pricing.py` працює як операційний інструмент без подвійного seed-проходу.

**P8. Usage extraction для Gemini повертав 0/0. Статус: ✅ виконано 2026-04-19.**

Проблема була в тому, що Gemini wrapper губив `usageMetadata`, а gateway не складав `candidatesTokenCount` і `thoughtsTokenCount`. Це вже виправлено: `_chat_once_gemini` повертає `.usage`, а `billing/gateway.py:_extract_usage` коректно читає і object-style, і dict-style Gemini payload. Reasoning-виклики Gemini тепер не знецінюються до нульового usage лише через transport wrapper.

**P9. Не всі 131 зміни закоммічені, бранч `gpt_wiser` змішує stage 1-4.5A і ранні memory-сесії. Статус: ⚠️ частково — основні multitenant-зміни вже комітнуті у гілку `multitenant`, лишається тільки фінальна сесія 2026-04-19 (thread-safe billing fix) у комітах `1bfb70d` (Implement multitenant runtime, admin, and media updates) і `b6fa3d0` (Multitenant billing: thread-safe transaction logging).**

Раніше всі multitenant-зміни жили на робочій копії без комітів. Зараз гілка `multitenant` уже містить:

- `1bfb70d` — Stage 1 + 2 + 3 + 4 + 4.5A bulk-комміт (admin dashboard, model preferences, провайдер registry, billing core, voice/persona).
- `b6fa3d0` — фінальний thread-safe `_maybe_emit_billing` + 15-key seed + revolver E2E + planner billing test + test_010 fix.

Що лишається поза комітами навмисно: `.env` (тестові секрети для @chibigochibot) і `mariadb-12.2.2-winx64.zip` (локальний інсталятор).

Деплой Stage 7 тепер зводиться до `git checkout multitenant && pm2 restart` після ротації тестових ключів і генерації окремого prod `BILLING_MASTER_KEY`. Rollback — `git checkout master && pm2 restart`.

### 12.3. КРИТИЧНА проблема — блокування event loop на LLM-викликах

Це знайдено в процесі цього аудиту і це **головний блокер для продакшну**. Суть: поточна архітектура не витримає навіть 10 паралельних юзерів, не кажучи про 100. Навіть якщо фікс не простий — його треба зробити до першого юзера.

**Що саме зламано.**

`agent/llm.py:508` — функція `chat_once` синхронна. Усередині вона викликає:
- для OpenAI-сумісних провайдерів: sync OpenAI SDK (`client.chat.completions.create(...)`) — блокуючий HTTP-запит
- для Gemini: `requests.post(...)` (рядок 436) — блокуючий HTTP-запит

Час виконання одного виклику: 2-5 секунд на швидких моделях, 10-30+ секунд на reasoning-моделях і великих промптах.

**Як це викликається з коду.**

`chat_once` викликається напряму з async функцій без `asyncio.to_thread`:
- `agent/runner.py:1082` — `run_search_synthesis` (async)
- `agent/runner.py:1156` — `run_capability` (async)
- `agent/runner.py:1249, 1338` — `run_agent` (async)
- `agent/planner.py:205, 244` — planner loop (async)
- `agent/search_task.py:435, 788, 838` — search synthesis (async)
- `billing/gateway.py:260` — всередині `chat_once_billed` (async), теж без `to_thread`

Коли ми в async функції робимо `response = chat_once(...)`, **event loop заморожується на весь час HTTP-виклику**. Поки чекаємо OpenAI 5 секунд, Telegram polling стоїть, всі інші coroutines чекають, жодна DB-query не стартує, webhook теж би не приймався (якби був вебхук).

**Симптоми для користувача при 100 паралельних запитах.**

Юзер A пише `"складне питання"` → запускається `run_agent` → блокуючий chat_once на 20 секунд. За ці 20 секунд 99 інших юзерів написали свої повідомлення. PTB зберіг їх у черзі. Після того як A закінчив, B починає, знову 20 секунд блокування. І так далі.

Тобто 100 запитів виконаються приблизно за **100 × середній_час = 100 × 10 = ~1000 секунд** послідовно. Замість ідеальних 10-15 секунд з паралелізмом.

Гірше: при такому затиску PTB може почати дропати оновлення (Telegram сам таймаутить long polling), і деякі повідомлення просто втратяться.

**Що вже зроблено правильно (і доводить, що патерн відомий у проєкті).**

- `media/voice.py:114` — `await asyncio.to_thread(_transcribe_sync, path)` для Whisper STT
- `media/voice.py:136` — `asyncio.to_thread(_synthesize_chunk_sync, chunk, index)` для TTS
- `media/router.py:142, 150, 199, 214` — `asyncio.to_thread` для `describe_images` і `analyze_video`
- `media/downloader.py:49, 76` — `asyncio.to_thread` для cleanup
- `media/album_registry.py` — threading.Lock для sync dict (ок)
- `memory/manager.py:88` — per-chat `asyncio.Lock` проти конкурентних консолідацій того самого chat_id

Тобто аудит 2026-04-12 (B1) уже полагодив video та image. А основний шлях `chat_once` — лишили без to_thread, бо на той момент було "одне оточення, один користувач, не критично".

**DB pool теж мале.**

`db/connection.py:61` — `maxsize=int(_env("DB_POOL_SIZE", "10"))`. Навіть якби LLM не блокував event loop, 11-й юзер чекав би вільного з'єднання, бо кожен turn робить серію DB-запитів (memory fetch, transaction log, user settings, chat policy check).

**Як правильно фіксити (план з двох частин).**

**Частина А — прибрати блокування event loop у LLM-викликах.**

Варіант 1 (мінімум змін, ~30 хвилин): загорнути всі 8+ callsite-ів у `asyncio.to_thread`:
```python
response = await asyncio.to_thread(
    chat_once,
    messages,
    tools=None,
    use_reasoning=use_reasoning,
    model=model,
    capability=capability,
)
```
Це миттєво розблокує event loop. Trade-off: thread pool за замовчуванням має 40 workers (ThreadPoolExecutor default), тобто 40 одночасних LLM-викликів. Для старту достатньо, для 100+ треба буде явно налаштувати `loop.set_default_executor(ThreadPoolExecutor(max_workers=128))` у `run.py`.

Варіант 2 (правильний, ~4 години): переробити `chat_once` на `async def chat_once_async` з `AsyncOpenAI` SDK і `httpx.AsyncClient` для Gemini. Тоді ніяких потоків, чистий async на I/O. Але треба переписати всі callsites, тести, адаптери, Gemini wrapper.

**Рекомендую Варіант 1 зараз** (бо це блокер деплою), а Варіант 2 — технічний борг на Stage 8.

**Частина Б — масштабувати DB pool і keypool.**

- У `.env` продовзіка: `DB_POOL_SIZE=50` (мінімум, якщо очікуємо 100 юзерів). Можна 100.
- Додати `DB_POOL_MINSIZE=5` (aiomysql його підтримує через kwarg `minsize`).
- Перевірити, що MariaDB `max_connections` на сервері дозволяє стільки (зараз за замовчуванням 151, треба глянути `SHOW VARIABLES LIKE 'max_connections';`).
- У `billing/keypool.py` зробити per-provider semaphore: якщо ключів 5, а одночасних юзерів 100, то 20 ділять кожен ключ. Краще черга на semaphore, ніж ulyanі 429 від провайдера.

**Частина В — залагодити `_run_async_sync` (див. P1).**

Якщо переробимо на `chat_once_async`, то `resolve_provider_binding` теж стане async — і проблема P1 зникне автоматично, без потоків.

### 12.4. Що гарантовано працює без регресій

Аудит переконався, що ці патерни живі й тестами покриті:
- DB повністю async (`aiomysql` pool), міграції проходять
- Media pipeline (voice, video, images) — `asyncio.to_thread` уже скрізь
- Per-chat `asyncio.Lock` у memory manager — немає race на ту саму consolidation
- `BillingContext` через ContextVar пропагується коректно через `begin_turn`/`end_turn`
- Keypool `record_success`/`record_error`/`record_rate_limit` інтегровані в gateway
- `user_settings` override коректно валідує whitelist провайдера
- Adapter-level reasoning args і gemini-native dispatch не ламаються під multitenant
- Admin UI sort і фільтри — через whitelist колонок, без SQL-ін'єкції

### 12.5. Порядок наступних дій (для наступної моделі)

Пріоритезовано за критичністю. **Крок 1 і 2 — обов'язково до будь-якого деплою з реальними юзерами.**

1. **✅ Частина А з 12.3** — виконано 2026-04-19. `chat_once` більше не викликається напряму з async execution path: bridge доданий у `runner.py`, `message_logic.py`, `search_task.py`, `billing/gateway.py`, `memory/summarizer.py`, `memory/importance.py`, `memory/reflection.py`. Додано `tests/test_094_concurrent_llm.py` на concurrency і propagation `BillingContext`.
2. **✅ Частина Б з 12.3** — виконано 2026-04-19. `db/connection.py` більше не живе на `DB_POOL_SIZE=10`: pool має default 50 через `core.env.db_pool_size()`, а `run.py` конфігурує default executor через `ThreadPoolExecutor(max_workers=128)` з окремим regression coverage в `tests/test_095_runtime_sizing.py`.
3. **✅ P7** — `pricing` seed закрито 2026-04-19. Missing rows тепер автоматично вставляються під час bootstrap, а live verification уже підтвердив непорожню `pricing`.
4. **✅ P8** — Gemini usage extraction закрито 2026-04-19. Wrapper і gateway враховують `thoughtsTokenCount`, тому Gemini reasoning більше не падає в `0 / 0`.
5. **✅ P6** — keypool-first policy для billed turns закрито 2026-04-19. Env більше не є тихим основним шляхом, якщо turn уже атрибутований білінгом.
6. **✅ P4** — sub-transaction breakdown у `/balance last` і `/balance turn <id>` закрито 2026-04-19. Команда більше не показує заглушку Stage 4, а рендерить sub-транзакції turn-а в межах акаунта.
7. **✅ P2, P3** — voice і persona в Telegram `/settings` закрито 2026-04-19. `user_settings` тепер реально впливають на TTS voice selection і prompt persona override.
8. **✅ Thread-safe `_maybe_emit_billing`** — закрито 2026-04-19. Sync `chat_once`, що йде через `asyncio.to_thread` (planner/search_task/runner), тепер реально пише транзакції через `asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)`. Без цього фіксу `provider_keys.total_requests` залишався 0 на бойовому трафіку. Виявлено під час підняття другого бота @chibigochibot як multitenant стенда із 15 засіяними ключами на $1 тестового бюджету.
9. **✅ Revolver E2E під 429** — закрито 2026-04-19. `scripts/test_revolver_rate_limit.py` доводить, що ключ після 429 дійсно маркується `rate_limited`, failed-транзакція реально логується, а наступний `acquire()` повертає інший `key_id`.
10. **✅ Planner billing E2E** — закрито 2026-04-19. `scripts/test_planner_billing.py` доводить, що `planner_reasoning` транзакція реально пишеться через threadsafe-шлях під `asyncio.to_thread`.
11. **✅ P9** — основну частину закрито: гілка `multitenant` тепер містить `1bfb70d` (bulk Stage 1-4.5A) і `b6fa3d0` (thread-safe billing fix). Лишається тільки сам Stage 7 deploy.
12. **P1** — після переходу на `chat_once_async` (Варіант 2 з Частини А) — зняти `_run_async_sync`. Відкладено як perf-only.
13. **P5** — мігрувати model catalog з хардкоду `model_preferences.py` на БД (`provider_catalog` або `pricing`). Відкладено як UX-only, після першого публічного релізу.
14. **Stage 7 deploy** — ротувати 15 тестових ключів на нові prod ключі, згенерити окремий prod `BILLING_MASTER_KEY`, задеплоїти `multitenant` гілку через `deploy.cjs` на staging, прогнати full pytest на staging, тільки після цього на prod.

### 12.6. Як перевірити, що фікс працює (acceptance для наступної моделі)

Коли кроки 1-5 з 12.5 будуть зроблені, має бути:
- Новий тест `test_094_concurrent_llm.py`: запускає 20 mock-ованих `run_capability` через `asyncio.gather`, перевіряє що загальний час < 2× часу одного виклику (тобто реально паралельно).
- `SELECT COUNT(*), SUM(cost_uah) FROM transactions WHERE created_at > NOW() - INTERVAL 1 HOUR` на staging після 10 turns має показати 10 рядків, кожен з ненульовим `cost_uah` і правильним `tokens_in`/`tokens_out` для всіх провайдерів (включно з Gemini).
- `/admin/users/<id>` — після поповнення 100 UAH і 5 turns — `balance_uah` змінився на `-SUM(cost_uah)`, всі transactions видно з правильною атрибуцією `key_id` (не NULL).
- У `/balance turn <id>` видно breakdown: `planner_reasoning` → `memory_summary` → `search_query` → `chat_final` (залежно від шляху), кожен рядок із провайдером/моделлю/токенами/коштом.
- PM2 `pm2 logs` під час 20 паралельних запитів не має "request timeout" або "event loop was blocked for X seconds".

### 12.7. Acceptance status станом на 2026-04-19

Перевірено на локальному стенді @chibigochibot із 15 засіяними тестовими ключами:

- **Реальний live turn у Telegram:** баланс реально впав на 0.181 UAH на 2333-token запит, транзакція з ненульовим `cost_uah`, `tokens_in/tokens_out`, не-NULL `key_id` записана.
- **Revolver під 429:** `scripts/test_revolver_rate_limit.py` -> PASS. Ключ 6 після синтетичного 429 марковано `rate_limited`, failed-транзакція з error_text залогована, `acquire()` повернув ключ 7.
- **Planner billing через threadsafe-шлях:** `scripts/test_planner_billing.py` -> PASS. `planner_reasoning` транзакція на 0.0345 UAH реально записана при виклику `_validate_search()` усередині `asyncio.to_thread`.
- **Sync chat_once у worker thread більше не мовчить:** до фіксу `_maybe_emit_billing` падав у `RuntimeError: no running event loop` і no-op'ив. Після фіксу через `_MAIN_LOOP` + `run_coroutine_threadsafe` реально пише транзакції.
- **Pricing seed:** для `gpt-5-chat-latest`, `gpt-5`, `gpt-5-reasoning`, `gpt-4o-mini`, `gemini-2.5-flash`, `gemini-2.5-pro`, `claude-sonnet-4-5`, `claude-opus-4-5` рядки реально проставлені, `cost_uah` більше не дорівнює нулю.
- **Test 010:** перетворений з мовчазно-зеленого (бюджет 10000 ніколи не пробивався) у реально-валідний (`monkeypatch _recent_budget` до 200, консолідація реально запускається).
- **Регресійний пакет:** `pytest -q` локально -> `308 passed`.

Що з §12.6 ще НЕ перевірено цією сесією:
- паралельні 20 turns через `asyncio.gather` на staging — це Stage 7 acceptance, не локальний стенд.
- `/admin/users/<id>` UI прохід після поповнення 100 UAH і 5 turns — це Stage 7 acceptance.
- PM2 `pm2 logs` під реальним 20-паралельним навантаженням — це Stage 7 acceptance.
