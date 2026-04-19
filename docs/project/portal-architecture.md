# Portal Architecture — Smartest

**Статус:** дизайн зафіксовано, готово до імплементації  
**Дата:** 2026-04-18  
**Контекст:** продовження multitenant-plan.md Stage 4.5 (admin dashboard + user portal)

---

## 1. Загальна структура

Два окремих інтерфейси на одному домені, плюс прихований backdoor:

```
smartest.klawa.top/          → User Portal (Telegram Login)
smartest.klawa.top/admin     → Admin Panel (Telegram Login, tg_user_id-check)
[HIDDEN].smartest.klawa.top  → Admin Backdoor (password, не публікується)
```

Поточний HTTP-сервер (BaseHTTPRequestHandler) розширюється новими маршрутами. Caddy вже є на сервері — routing за path-prefix або subdomain на рівні Caddy config.

---

## 2. Telegram Login Widget (новий, квітень 2026)

### Що це

Новий Login Widget від Telegram дозволяє:
- **Авторизацію** користувача через Telegram-акаунт (sign-up + login в одному)
- **Запит номера телефону** (users approve → `phone_number` в токені)
- **Permission to message** — бот може потім написати юзеру в Telegram

Повністю безкоштовно. Замінює старий iframe-widget і не потребує сторонніх OIDC-провайдерів.

### Налаштування

1. Зареєструвати дозволені URL через `@BotFather` → команда `/setdomain`
2. Отримати `client_id` = числовий Bot ID

### Frontend

```html
<script async src="https://telegram.org/js/telegram-widget.js"></script>
<script>
  Telegram.Login.init({
    client_id: BOT_ID,          // числовий ID бота
    request_access: ['phone']   // + 'write' якщо треба надсилати повідомлення
  }, function(user) {
    // user — decoded JWT payload або null (якщо юзер відмовив)
    fetch('/auth/telegram', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(user)
    }).then(r => r.ok ? location.reload() : alert('Помилка входу'));
  });
  
  Telegram.Login.open(); // показати popup
</script>
```

### Backend — верифікація JWT

Telegram повертає `id_token` (JWT, підписаний Telegram):

```python
import httpx
from jose import jwt, JWTError

async def verify_telegram_token(id_token: str, bot_id: int) -> dict:
    # 1. Отримати публічні ключі
    jwks = httpx.get("https://oauth.telegram.org/.well-known/jwks.json").json()
    # 2. Верифікувати JWT
    claims = jwt.decode(
        id_token,
        jwks,
        algorithms=["RS256"],
        audience=str(bot_id),
        issuer="https://oauth.telegram.org"
    )
    # claims містить: sub, id, name, preferred_username, picture, phone_number
    return claims
```

Необхідна залежність: `python-jose[cryptography]` (або `PyJWT[crypto]`).

### Дані з токену

```json
{
  "iss": "https://oauth.telegram.org",
  "sub": "987654321",
  "aud": "YOUR_BOT_ID",
  "id": 987654321,
  "name": "Іван Іванов",
  "preferred_username": "ivan",
  "picture": "https://cdn.telegram.org/...",
  "phone_number": "+380501234567",
  "iat": 1745000000,
  "exp": 1745003600
}
```

---

## 3. Auth-архітектура

### Сесії

Два незалежні cookie namespace:
- `_smartest_user` — user portal session
- `_smartest_admin_backdoor` — backdoor session (тільки на hidden subdomain)

Сесії зберігаються як підписані JSON-cookies (HMAC-SHA256 з `SESSION_SECRET`).

### Хто є адміном

```python
# core/env.py або .env
ADMIN_TG_USER_IDS = "123456789,987654321"  # comma-separated числові IDs
```

При Telegram login: якщо `claims['id'] in ADMIN_TG_USER_IDS` → видається admin session з прапорцем `is_admin=True` → доступ до `/admin/*`.

### Backdoor (hidden subdomain)

- URL: `[HIDDEN_PREFIX].smartest.klawa.top` — не публікується, зберігається тільки в `.env`
- Авторизація: поточний механізм (username + password з `.env`, cookie `_smartest_admin_backdoor`)
- Доступ: ті ж `/admin/*` маршрути, але з backdoor session
- Caddy: окремий `reverse_proxy` block для цього subdomain

```
# .env
BACKDOOR_SUBDOMAIN=d3f4ult  # не публікується
```

Таким чином, навіть якщо Telegram Login Widget недоступний або бот-токен компрометований — адмін може увійти через backdoor.

---

## 4. User Portal (`/`)

### Маршрути

| Path | Метод | Опис |
|------|-------|------|
| `/` | GET | Dashboard: баланс, останні 5 turns, кнопки |
| `/auth/telegram` | POST | Прийняти Telegram token, виставити cookie |
| `/logout` | POST | Очистити cookie |
| `/topup` | GET/POST | Форма поповнення (Stage 5 — Monobank) |
| `/history` | GET | Список turns з pagination |
| `/history/<turn_id>` | GET | Breakdown turn по sub-транзакціях (planner → search → final) |
| `/settings` | GET/POST | Персональні налаштування (модель, голос, persona) |

### Dashboard

```
👤 Іван (@ivan)  |  Баланс: 47.32 ₴  |  Поповнити

📊 Витрати сьогодні: 2.18 ₴   Цього місяця: 28.41 ₴

Останні запити:
 ├─ 14:32  "Поясни квантову заплутаність"    0.43 ₴  gemini-2.5-pro
 ├─ 13:11  "Переклади цей текст..."            0.12 ₴  gpt-4o-mini
 └─ 11:05  [пошук] "Новини Tesla сьогодні"    0.31 ₴  gpt-4o

[Повна історія]  [Поповнити баланс]  [Налаштування]
```

### Turn breakdown (History detail)

```
Запит #c4f2a1 — "Поясни квантову заплутаність"
Час: 14:32:11   Тривалість: 4.2с   Сума: 0.43 ₴

  planner          gpt-4o-mini    240 in / 80 out    0.02 ₴
  search_compose   gpt-4o-mini    310 in / 45 out    0.01 ₴
  web search API   brave          1 query             0.00 ₴
  search_eval      gpt-4o-mini    890 in / 60 out    0.02 ₴
  chat_final       gemini-2.5-pro 2100 in / 580 out  0.38 ₴
```

---

## 5. Admin Panel (`/admin`)

Доступний через:
- Telegram Login + `is_admin=True` на `smartest.klawa.top`
- Password login на `[HIDDEN].smartest.klawa.top`

### Маршрути

| Path | Опис |
|------|------|
| `/admin` | Overview: загальна статистика |
| `/admin/users` | Список юзерів з сортуванням і фільтром |
| `/admin/users/<id>` | Детальна картка юзера |
| `/admin/users/<id>/credit` | POST — поповнити баланс вручну |
| `/admin/chats` | Список чатів з policy |
| `/admin/transactions` | Глобальний лог транзакцій |
| `/admin/topups` | Всі поповнення |
| `/admin/keys` | Пул провайдерських ключів |
| `/admin/keys/add` | POST — додати ключ |
| `/admin/keys/<id>/toggle` | POST — enable/disable |

### `/admin/users` — таблиця юзерів

Колонки (всі сортовані кліком на заголовок `?sort=col&dir=asc/desc`):

| Колонка | SQL | Тип |
|---------|-----|-----|
| Username | `users.tg_username` | text |
| Ім'я | `users.first_name` | text |
| Реєстрація | `users.first_seen_at` | date |
| Остання активність | `users.last_seen_at` | datetime |
| Баланс | `accounts.balance_uah` | decimal |
| Витрачено всього | `accounts.total_spent_uah` | decimal |
| Поповнено | `accounts.total_topup_uah` | decimal |
| Запитів всього | `COUNT(turns)` | int |
| Запитів сьогодні | `COUNT(turns WHERE DATE=today)` | int |
| Запитів 7д | `COUNT(turns WHERE created_at > -7d)` | int |
| Токени вхід | `SUM(transactions.tokens_in)` | int |
| Токени вихід | `SUM(transactions.tokens_out)` | int |
| Улюблена модель | `MODE(transactions.model)` | text |

Дії у рядку: [Деталі] [Поповнити]

**Поповнення вручну** — форма: сума (UAH) + нотатка (обов'язково). Записується як `topups(status='success', note='admin_manual_<admin_tg_id>')` і `credit_account(account_id, amount)`. Підтвердження: "Баланс @username поповнено на 50.00 ₴. Новий баланс: 97.32 ₴."

### `/admin/keys` — пул провайдерських ключів

Таблиця:

| Колонка | Опис |
|---------|------|
| Label | Дружня назва (напр. "openai-main-1") |
| Provider | openai / gemini / anthropic |
| Key (masked) | Показуємо тільки sha256[:8] + "..." + last_4 |
| Status | active / disabled / rate_limited / invalid |
| RPM / TPM limit | налаштований ліміт |
| Використано USD | `total_spent_usd` |
| Остання активність | `last_used_at` |
| Остання помилка | `last_error_at` + `last_error` (truncated) |
| Cooldown до | якщо є — datetime |

Дії: [Disable/Enable] [Delete]

**Додавання ключа:**
```
Provider:    [ OpenAI ▼ ]
Label:       [ openai-backup-3    ]
API Key:     [ sk-...             ]  ← не показується після збереження
RPM limit:   [ 60                 ]
TPM limit:   [ 100000             ]
[ Додати ключ ]
```

Ключ шифрується AES-256-GCM з `KEY_ENCRYPTION_SECRET` з `.env` і зберігається в `provider_keys.encrypted_key`. SHA-256 hash — у `provider_keys.key_hash` (для ідентифікації без розшифровки).

---

## 6. Технічний стек

### Backend

| Компонент | Рішення |
|-----------|---------|
| HTTP сервер | Існуючий `BaseHTTPRequestHandler` (розширюємо) |
| JWT верифікація | `python-jose[cryptography]` |
| Шифрування ключів | `cryptography` (AES-256-GCM) — вже є в `billing/crypto.py` |
| Сесії | HMAC-SHA256 підписані JSON cookies |
| Шаблони | Inline HTML (як зараз в admin_ui.py) |

### Нові залежності

```
python-jose[cryptography]>=3.3
```

(`cryptography` вже є як залежність `python-jose`)

### Caddy config (додати)

```caddy
# User Portal + Admin (Telegram Login)
smartest.klawa.top {
    reverse_proxy localhost:8080
}

# Admin Backdoor (password login)
{$BACKDOOR_SUBDOMAIN}.smartest.klawa.top {
    reverse_proxy localhost:8080
    # header X-Backdoor-Access true  ← щоб handler знав
}
```

Або: один handler, відрізняє за `Host` header.

---

## 7. Порядок імплементації

### Stage 4.5A — Admin dashboard (без Telegram Login)

Пріоритет: **зараз**. Корисний одразу для тебе, не потребує нового login-flow.

1. Нові репозиторні функції: `list_users_with_stats`, `list_chats_with_policy`, `list_transactions_filtered`, `credit_account_admin`
2. `/admin/users` сторінка з сортуванням
3. `/admin/users/<id>` детальна картка
4. `/admin/users/<id>/credit` — форма поповнення
5. `/admin/chats` — таблиця чатів
6. `/admin/transactions` — global лог
7. `/admin/keys` — key pool management UI

Авторизація тимчасово: існуючий admin cookie (password). Після Stage 4.5B замінимо на Telegram Login.

### Stage 4.5B — Telegram Login + User Portal

1. `@BotFather` → `/setdomain smartest.klawa.top` (роблять вручну)
2. `verify_telegram_token()` — JWT верифікація
3. `/auth/telegram` endpoint
4. User portal сторінки (`/`, `/history`, `/topup`, `/settings`)
5. Admin перевірка: `ADMIN_TG_USER_IDS` з env
6. Backdoor subdomain в Caddy + env

### Stage 4.5C — Інтеграція /admin з Telegram Login

Коли 4.5B готовий — замінити admin login на Telegram-based, зберегти backdoor як fallback.

---

## 8. Безпека

- JWT верифікація — **завжди на сервері**, frontend тільки передає токен
- JWKS кешуються з TTL 1 год (не fetching on every request)
- Backdoor URL не логується в публічних логах (тільки у journald)
- `ADMIN_TG_USER_IDS` і `BACKDOOR_SUBDOMAIN` — тільки в `.env`, ніколи в коді
- Всі admin actions логуються в `app_audit_log` (новий) або в `topups.note`
- Rate limit на `/auth/telegram`: max 10 req/хв з одного IP

---

## 9. Відкриті питання

1. **Per-user settings** (модель, голос, persona) — зберігати в `user_settings(user_id, key, value)` таблиці з Stage 1, але ще не реалізовано
2. **Telegram "write" permission** — чи запитувати `request_access: ['phone', 'write']` одразу, чи тільки `phone` при реєстрації, а `write` — opt-in пізніше
3. **Сесії users** — TTL скільки? Пропоную 7 днів (refresh на кожен request)
4. **Mobile UX** — user portal має бути responsive, inline HTML складно підтримувати. Можливо варто перейти на Jinja2 templates
