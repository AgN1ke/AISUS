# Security Audit + Dead Code — 2026-04-13

---

## ЧАСТИНА 1: ВРАЗЛИВОСТІ

### CRITICAL

#### V1. SSH credentials захардкожені в deploy scripts

**Файли:** `deploy/deploy.cjs:88`, `deploy/clear_memory.cjs:70`

```javascript
.connect({ host: '87.106.11.84', port: 22, username: 'root', password: '8Vib2YTN', ... });
```

Пароль root-доступу до продакшн сервера в plain text. Якщо репозиторій стане публічним або хтось отримає доступ до коду — повний контроль сервера.

**Фікс:** Переписати deploy скрипти на SSH key authentication. Або хоча б читати credentials з env vars:
```javascript
.connect({ host: process.env.DEPLOY_HOST, username: process.env.DEPLOY_USER, password: process.env.DEPLOY_PASS })
```

---

### HIGH

#### V2. Command injection через shell=True у FFmpeg

**Файл:** `media/video.py:78, 90, 105`

```python
cmd = f"{FFPROBE_BIN} -v error -show_entries format=duration ..."
subprocess.check_output(cmd, shell=True, text=True)  # line 78

cmd = f"{FFMPEG_BIN} -y -i {shlex.quote(video_path)} ..."
subprocess.check_call(cmd, shell=True)  # lines 90, 105
```

Хоча шляхи загорнуті в `shlex.quote()`, самі команди будуються як f-string і виконуються через `shell=True`. Параметр `fps` (line 98: `fps = max(0.1, 1.0 / max(0.1, every_sec))`) — числовий з env var, але pattern небезпечний. Якщо хтось в майбутньому додасть user input в будь-який з цих cmd — shell injection.

**Фікс:** Переписати на `subprocess.run([...], shell=False)`:
```python
subprocess.run([FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path], check=True, capture_output=True, text=True)
```

#### V3. SSRF у fetch_page — немає блоклісту приватних IP

**Файл:** `agent/tools/fetch_page.py:42`

```python
resp = requests.get(url, headers=_request_headers(), timeout=TIMEOUT_SEC)
```

URL приходить з результатів пошуку, які формуються на основі user input. Немає перевірки на:
- `127.0.0.1`, `localhost`
- Приватні діапазони: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- Cloud metadata: `169.254.169.254`

Атакуючий може через пошуковий запит спровокувати бота відкрити внутрішній URL і отримати відповідь.

**Фікс:** Додати URL validation перед requests.get:
```python
import ipaddress, urllib.parse

def _is_safe_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        return ip.is_global
    except ValueError:
        # hostname, not IP — resolve and check
        import socket
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname))
            return ip.is_global
        except Exception:
            return True  # DNS failure — let requests handle it
```

---

### MEDIUM

#### V4. Admin UI: немає rate limiting на login

**Файл:** `app/admin_ui.py` — `_handle_login()`

Невдала авторизація просто повертає "Невірний логін або пароль" без будь-якого обмеження спроб. Brute-force атака можлива, якщо admin UI відкритий зовні.

**Пом'якшення:** Admin UI за замовчуванням слухає на `127.0.0.1` (не доступний ззовні). Але якщо `SMARTEST_ADMIN_HOST=0.0.0.0` — вразливий.

**Фікс:** Додати лічильник невдалих спроб з IP. Після 5 невдач — блок на 5 хвилин.

#### V5. Verbose error messages в flash-повідомленнях

**Файл:** `app/admin_ui.py` — кілька місць

```python
flash = f"Не вдалося зберегти або перевірити service account JSON: {exc}"
```

Детальні тексти Python-помилок виводяться юзеру в UI. Можуть розкривати внутрішню структуру (шляхи файлів, імена таблиць, конфіг Google Cloud).

**Фікс:** Логувати `exc` в logger, юзеру показувати generic message.

#### V6. .env-example містить підказку до default credentials

**Файл:** `.env-example:7-9`

```
SMARTEST_ADMIN_USERNAME=admin
SMARTEST_ADMIN_PASSWORD=change_me
```

Не вразливість сама по собі, але якщо хтось забуде змінити — admin UI відкритий з відомими credentials.

---

### LOW

#### V7. Session secret генерується лениво

**Файл:** `app/admin_ui.py` — `ensure_session_secret()`

Secret генерується при першому логіні і записується в .env. Теоретичний race condition при одночасному логіні. На практиці неексплуатабельно (single-threaded HTTP server).

#### V8. Path traversal — захист є, але тільки при cleanup

**Файл:** `media/downloader.py:12-18`

`_safe_media_path()` перевіряє що шлях в межах MEDIA_TMP. Використовується тільки при cleanup, не при download. Download йде через Telegram API (trusted source), тому не критично.

---

### OK (перевірено, проблем немає)

- **SQL injection:** Всі запити в `db/` використовують `%s` placeholders з параметрами. Безпечно.
- **XSS в admin UI:** Весь user input проходить через `html.escape()`. Безпечно.
- **Unsafe deserialization:** Немає `pickle.load()`, `eval()`, `exec()`, `yaml.load()` ніде в коді.
- **Authentication admin UI:** Basic auth + HMAC-signed session cookies + HttpOnly. Нормально для internal tool.

---

## ЧАСТИНА 2: ФАЙЛИ НА ВИДАЛЕННЯ

### Точно видалити (dead code, ніде не імпортується)

| Файл | Рядків | Що це | Чому dead |
|------|--------|-------|-----------|
| `knowledge/glossary.py` | ~60 | Обробка glossary термінів | Ніде не імпортується. `process_user_text`, `gc_suggestions` не використовуються. |
| `memory/prompts.py` | ~30 | Re-export констант з `core.prompts` | Ніде не імпортується. Всі файли імпортують напряму з `core.prompts`. |
| `commands/` (вся папка) | ~0 | Порожній `__init__.py` | Ніде не імпортується. Порожня папка. |
| `whisper_tool.py` | 9 | Stub для тестів | Ніде не імпортується і не використовується. |
| `src/message_handler.py` | 55 | Legacy PTB handler | Ніде не імпортується. Замінений на `app/message_logic.py`. |
| `src/message_wrapper.py` | 64 | Legacy message wrapper | Ніде не імпортується. Замінений на `adapters/base.py:UnifiedMessage`. |
| `src/openai_wrapper.py` | 14 | Legacy OpenAI wrapper | Ніде не імпортується. Замінений на `agent/llm.py`. |
| `src/voice_processor.py` | 50 | Legacy voice processing | Ніде не імпортується. Замінений на `media/voice.py`. |
| `src/config_reader.py` | 35 | Legacy config reader | Ніде не імпортується. Замінений на `core/env.py`. |

### Видалити з оновленням тесту

| Файл | Рядків | Що це | Залежність |
|------|--------|-------|------------|
| `src/heroku_config_parser.py` | 88 | Legacy Heroku config parser | Імпортується **тільки** в `tests/test_037_prompts.py:12`. Тест `test_legacy_config_reader_uses_centralized_defaults` треба видалити разом. |

### Впорядкувати .gitignore

Зараз `.gitignore` не покриває deploy артефакти. Треба додати:
```
deploy/node_modules/
deploy/*.tar.gz
deploy/package.json
deploy/package-lock.json
```

Ці файли вже untracked (в `git status` зі знаком `??`), але без .gitignore можуть випадково потрапити в коміт.

### НЕ видаляти

| Файл | Чому залишаємо |
|------|----------------|
| `clear_memory.py` | Використовується `deploy/clear_memory.cjs` — деплоїть і запускає на сервері |
| `core/logging_setup.py` | Новий файл, ще не закомічений, але використовується |
| `core/podcast.py` | Podcast integration — активна фіча |
| `app/podcast_dossier.py` | Podcast dossier — активна фіча |
| `app/podcast_intent.py` | Podcast intent detection — активна фіча |

---

## ЧАСТИНА 3: ПРІОРИТЕТИ

### Зробити зараз
1. **V1** — Прибрати credentials з deploy scripts (CRITICAL)
2. **V2** — Переписати FFmpeg subprocess на shell=False (HIGH)
3. Видалити всі dead files (10 файлів + 1 папка)
4. Оновити .gitignore

### Зробити при нагоді
5. **V3** — SSRF blocklist для fetch_page (HIGH, але exploitability залежить від контексту)
6. **V4** — Rate limiting на admin login (MEDIUM)
7. **V5** — Generic error messages в admin UI (MEDIUM)
