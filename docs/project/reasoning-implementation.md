# Reasoning / Thinking Mode — План імплементації

## 1. Що маємо зараз

Reasoning plumbing в коді є, але **фактично мертвий**:

- `OPENAI_REASONING_MODEL` не заданий на сервері — `_maybe_reasoning_args()` завжди повертає `{}`
- Навіть коли planner ставить `use_reasoning=True`, API-запит іде без жодних reasoning-параметрів
- `_needs_reasoning()` спрацьовує тільки на `/think` prefix
- Reasoning прив'язаний до **глобального** env var, а не per-capability
- Стара архітектура вимагала **окрему модель** для reasoning (`OPENAI_REASONING_MODEL`) — це було потрібно для o1/o3, але GPT-5.x вміє reasoning на тій самій моделі
- Gemini thinking budget захардкожений на 0 (вимкнено) для Flash, None для решти
- В admin UI **жодних** контролів для reasoning
- Claude/Anthropic взагалі не підтримується нашою системою (ми все гоним через OpenAI SDK)

Файли з reasoning логікою:
- `core/env.py:141-238` — `reasoning_model()`, `reasoning_effort()`, `provider_supports_reasoning()`, `gemini_thinking_budget()`
- `agent/llm.py:66-94` — `_maybe_reasoning_args()`, `_pick_model()` 
- `agent/llm.py:237-241` — Gemini `thinkingConfig` в payload
- `agent/llm.py:368-400` — `chat_once()` — головна точка входу
- `agent/planner.py:41-43` — `_needs_reasoning()` — детектор `/think`
- `agent/runner.py` — прокидає `use_reasoning` через весь ланцюг

## 2. Що хочемо

### Для адміна (UI)

У кожного "розумного" capability (chat_final, agent_reasoning, search_synthesis) з'являється:
- **Checkbox "Reasoning"** — дозволяє чи забороняє reasoning для цього capability
- Якщо обрана модель **не підтримує** reasoning — checkbox сірий, неактивний
- **Select "Effort"** (low / medium / high) — видно тільки коли checkbox ON
- При зміні провайдера/моделі — JS автоматично перевіряє і дізейблить/вмикає checkbox

### Для бота (runtime)

- Коли reasoning **вимкнений** для capability — модель нічого не знає про reasoning, жодних додаткових параметрів, жодних зайвих процесів. Як ніби reasoning не існує.
- Коли reasoning **ввімкнений** — він активується **тільки коли потрібно**:
  1. Юзер явно просить: `/think`, `подумай`, `think`, `reason`, `роздумай`, `проаналізуй глибше`
  2. Planner LLM сам вирішує, що задача потребує глибокого reasoning
  3. В усіх інших випадках — навіть при увімкненому reasoning, запит іде **без** reasoning (effort=none для OpenAI, thinkingBudget=0 для Gemini), щоб не зливати токени

### Ключовий принцип: reasoning = дозвіл, а не примус

`reasoning_enabled=True` для capability означає: "ця модель МОЖЕ думати глибше, якщо потрібно". Це не означає, що кожен запит піде з reasoning. Planner або explicit trigger вирішують, коли саме активувати.

## 3. Актуальні API (квітень 2026)

### 3.1. OpenAI — GPT-5.4, GPT-5.4-mini, GPT-5.4-nano, o4-mini

**Усі GPT-5.x моделі підтримують reasoning** — це головна зміна порівняно з 2024-2025, де reasoning був тільки в o-серії. GPT-5.4 — перша mainline модель з вбудованим reasoning.

```python
response = client.chat.completions.create(
    model="gpt-5.4-mini",
    messages=[...],
    reasoning={"effort": "medium"},
)
```

**Параметр:** `reasoning.effort`
**Значення:** `"none"` (default), `"low"`, `"medium"`, `"high"`, `"xhigh"`

**Обмеження коли effort != "none":**
- `temperature` — **заборонено**, запит впаде з помилкою
- `top_p` — заборонено
- `logprobs` — заборонено
- Для o-серії: `max_completion_tokens` замість `max_tokens`

**Вартість:** xhigh коштує 3-5x більше ніж low. none = звичайна відповідь без reasoning tokens.

**Моделі:**
| Модель | Reasoning | Примітка |
|--------|-----------|----------|
| gpt-5.4 | effort: none-xhigh | Flagship |
| gpt-5.4-mini | effort: none-xhigh | Швидка/дешева |
| gpt-5.4-nano | effort: none-xhigh | Найдешевша |
| gpt-4.1 | **НІ** | Старе покоління |
| gpt-4.1-mini | **НІ** | Старе покоління |
| o4-mini | effort: low-high | Тільки reasoning (без none) |

### 3.2. Google Gemini

**Два покоління з різними параметрами:**

#### Gemini 3.x (3.1 Pro, 3 Flash, 3.1 Flash-Lite)
```json
{
  "generationConfig": {
    "thinkingConfig": {
      "thinkingLevel": "medium"
    }
  }
}
```
**Параметр:** `thinkingConfig.thinkingLevel`
**Значення:** `"minimal"`, `"low"`, `"medium"`, `"high"`
**Несумісний** з старим `thinkingBudget` — не можна використовувати обидва.

#### Gemini 2.5 (Pro, Flash, Flash-Lite)
```json
{
  "generationConfig": {
    "thinkingConfig": {
      "thinkingBudget": 4096
    }
  }
}
```
**Параметр:** `thinkingConfig.thinkingBudget`
**Значення:** `0` (вимкнути, тільки Flash), `-1` (dynamic), `128-24576` (Flash), `128-32768` (Pro)
**2.5 Pro не може вимкнути thinking** — мінімум 128.

| Модель | Параметр | Вимкнення |
|--------|----------|-----------|
| gemini-3.1-pro-preview | thinkingLevel | minimal |
| gemini-2.5-pro | thinkingBudget | НЕ МОЖНА (мін 128) |
| gemini-2.5-flash | thinkingBudget | 0 |
| gemini-2.5-flash-lite | thinkingBudget | 0 |

### 3.3. DeepSeek

Reasoning контролюється **назвою моделі**, а не параметром:
- `deepseek-chat` — без reasoning
- `deepseek-reasoner` — з reasoning (CoT в `<think>` тегах)

Немає `reasoning.effort` чи аналога. Reasoning або є, або ні.

Обмеження `deepseek-reasoner`: temperature/top_p ігноруються, **tools не підтримуються**.

### 3.4. xAI Grok

Складна ситуація — reasoning тільки в спец-моделях:
- `grok-4` / `grok-3` — reasoning вбудований, **не конфігурується**
- `grok-4.20-reasoning` — reasoning автоматичний
- `grok-3-mini` — reasoning автоматичний
- `reasoning_effort` **не підтримується** — запит з цим параметром впаде з помилкою

Для нашої системи: **Grok reasoning не контролюємо**. Моделі або думають, або ні.

### 3.5. OpenRouter

OpenRouter транслює `reasoning.effort` у нативний формат кожного провайдера:

```python
response = client.chat.completions.create(
    model="openai/gpt-5.4-mini",
    messages=[...],
    extra_body={"reasoning": {"effort": "high"}}
)
```

**Значення:** `"none"`, `"minimal"`, `"low"`, `"medium"`, `"high"`, `"xhigh"`
**Підтримка:** OpenAI, Grok, Gemini 3, Anthropic (з перетворенням). DeepSeek — через вибір моделі.

### 3.6. Anthropic Claude (Opus 4.6, Sonnet 4.6)

Claude підтримує adaptive thinking:
```python
# Anthropic SDK (НЕ OpenAI-compatible)
response = client.messages.create(
    model="claude-opus-4-6",
    thinking={"type": "adaptive"},
    effort="high",
    messages=[...]
)
```
**Значення effort:** `"low"`, `"medium"`, `"high"`, `"max"` (max тільки Opus)

**Проблема для нас:** Наша система використовує OpenAI SDK для всіх провайдерів. Anthropic thinking потребує нативний SDK. Два варіанти:
1. Через OpenRouter — OpenRouter транслює reasoning для Claude
2. Додати Anthropic adapter — потребує anthropic SDK + окремий code path

**Рішення:** Поки що Claude reasoning підтримується **тільки через OpenRouter**. Нативний Anthropic adapter — окрема задача на майбутнє.

## 4. Розпізнавання потреби в reasoning

### 4.1. Явне прохання юзера

Planner (або heuristic) розпізнає explicit reasoning trigger:

**Українською:** `подумай`, `роздумай`, `проаналізуй глибше`, `поміркуй`, `поясни крок за кроком`, `детально розбери`, `/think`

**Англійською:** `think`, `reason`, `think step by step`, `analyze deeply`, `think carefully`, `/think`

Це НЕ fuzzy matching — це конкретні слова/фрази на початку або в тілі повідомлення. Якщо юзер просто ставить питання — reasoning не вмикається, навіть якщо питання складне. Reasoning вмикається **тільки коли юзер явно просить** або planner вважає задачу дуже складною.

### 4.2. Planner LLM

Planner вже повертає `"use_reasoning": true/false` в JSON. Це залишається. Але тепер planner знає, що reasoning = дорогий ресурс, і ставить `true` тільки коли:
- Юзер явно просить (trigger слова вище)
- Задача вимагає багатокрокового математичного/логічного reasoning

Planner prompt вже має інструкцію: `use_reasoning=true лише якщо користувач прямо просить подумати глибше (/think) або задача вимагає складних багатокрокових міркувань.`

### 4.3. Gate: capability check

Навіть якщо planner або юзер каже "думай" — якщо для цього capability reasoning вимкнений в адмінці, запит іде без reasoning. Тихо, без повідомлень.

## 5. Зміни по файлах

### 5.1. `core/env.py` — Нові функції, видалення старих

**Видалити (стара глобальна логіка):**
- `reasoning_model()` — в GPT-5.x reasoning на тій самій моделі, окрема модель не потрібна
- `reasoning_effort()` — глобальний → per-capability
- `provider_supports_reasoning()` — замінюється на `can_reason()`

**Додати:**
```python
def can_reason(provider: str, model: str) -> bool:
    """Чи підтримує ця комбінація провайдер+модель reasoning?"""
    p = provider.lower().strip()
    m = model.lower().strip()
    if p == "openai":
        # GPT-5.x всі підтримують; o-серія теж
        return any(tag in m for tag in ("gpt-5", "o1", "o3", "o4"))
    if p == "gemini":
        return any(tag in m for tag in ("2.5", "3."))
    if p == "deepseek":
        return "reasoner" in m
    if p == "openrouter":
        return any(tag in m for tag in ("gpt-5", "o1", "o3", "o4", "2.5", "3.", "reasoner"))
    return False

def capability_reasoning_enabled(capability: str) -> bool:
    """Чи дозволений reasoning для цього capability? Читає CAPABILITY_{CAP}_REASONING_ENABLED."""
    cap = (capability or "").strip().upper()
    return env_bool(f"CAPABILITY_{cap}_REASONING_ENABLED", default=False)

def capability_reasoning_effort(capability: str) -> str:
    """Рівень effort для capability. Default: medium."""
    cap = (capability or "").strip().upper()
    raw = os.getenv(f"CAPABILITY_{cap}_REASONING_EFFORT", "medium").strip().lower()
    if raw in ("none", "low", "medium", "high", "xhigh"):
        return raw
    return "medium"
```

**Оновити `gemini_thinking_budget()`:**
Додати параметр `reasoning_active: bool`. Якщо reasoning НЕ активний — повертати 0 (Flash) або мінімальне значення (Pro). Якщо активний — повертати бюджет відповідно до effort рівня.

### 5.2. `agent/llm.py` — Основна логіка

#### `_maybe_reasoning_args()` — повний перепис

```python
def _maybe_reasoning_args(binding: ProviderBinding, use_reasoning: bool) -> dict:
    """Повертає kwargs для reasoning. Порожній dict = reasoning не потрібен."""
    if not use_reasoning:
        return {}
    if not capability_reasoning_enabled(binding.capability):
        return {}
    if not can_reason(binding.provider, binding.model):
        return {}
    effort = capability_reasoning_effort(binding.capability)
    return {"reasoning": {"effort": effort}}
```

#### `_pick_model()` — спрощення

Прибрати всю логіку з `reasoning_model()`. Єдиний special case — DeepSeek:
```python
def _pick_model(binding: ProviderBinding, use_reasoning: bool) -> str:
    if (
        use_reasoning
        and binding.provider.lower() == "deepseek"
        and "reasoner" not in binding.model.lower()
        and capability_reasoning_enabled(binding.capability)
    ):
        return "deepseek-reasoner"
    return binding.model
```

#### `chat_once()` — guards для reasoning

```python
def chat_once(messages, tools=None, use_reasoning=False, model=None, 
              temperature=0.3, capability="chat_final", **extra_kwargs):
    binding = _resolve_binding(capability, model_override=model)
    model_name = _pick_model(binding, use_reasoning)
    
    # Gemini path
    if is_gemini_native(binding):
        return _chat_once_gemini(
            binding, messages,
            temperature=temperature, model=model_name, tools=tools,
            reasoning_active=use_reasoning and capability_reasoning_enabled(binding.capability),
            **extra_kwargs,
        )
    
    # OpenAI-compatible path
    reasoning_args = _maybe_reasoning_args(binding, use_reasoning)
    kwargs = {"model": model_name, "messages": messages}
    
    if reasoning_args:
        # Reasoning active — прибрати temperature, використати max_completion_tokens
        kwargs.update(reasoning_args)
        max_tok = extra_kwargs.pop("max_tokens", None)
        if max_tok:
            kwargs["max_completion_tokens"] = max_tok
    else:
        # Звичайний режим — temperature як завжди
        kwargs["temperature"] = temperature
        max_tok = extra_kwargs.pop("max_tokens", None)
        if max_tok:
            kwargs["max_tokens"] = max_tok
    
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    kwargs.update(extra_kwargs)
    return _get_client(binding).chat.completions.create(**kwargs)
```

#### Gemini path — `_messages_to_gemini_payload()` / `_chat_once_gemini()`

Додати `reasoning_active` параметр. Якщо reasoning активний:
- Gemini 3.x: `thinkingLevel` = effort mapping (low→"low", medium→"medium", high→"high")
- Gemini 2.5: `thinkingBudget` = effort mapping (low→1024, medium→8192, high→24576)

Якщо reasoning НЕ активний:
- Gemini 3.x: `thinkingLevel` = "minimal"
- Gemini 2.5 Flash: `thinkingBudget` = 0
- Gemini 2.5 Pro: `thinkingBudget` = 128 (мінімум, не можна вимкнути)

### 5.3. `agent/planner.py` — Gate check + trigger detection

**`_needs_reasoning()`** — розширити детектор:
```python
_REASONING_TRIGGERS_UK = {"подумай", "роздумай", "поміркуй", "проаналізуй глибше", 
                          "детально розбери", "крок за кроком", "поясни детально"}
_REASONING_TRIGGERS_EN = {"think", "reason", "think step by step", "analyze deeply",
                          "think carefully", "step by step"}
_REASONING_TRIGGERS_CMD = {"/think"}

def _needs_reasoning(user_text: str) -> bool:
    text = (user_text or "").strip().lower()
    if any(text.startswith(cmd) for cmd in _REASONING_TRIGGERS_CMD):
        return True
    # Перевіряємо фрази (не просто слова, щоб "я думаю" не тригерило)
    for phrase in _REASONING_TRIGGERS_UK | _REASONING_TRIGGERS_EN:
        if phrase in text:
            return True
    return False
```

**Gate в `plan_message()`:**
```python
# Після отримання decision від planner або heuristic:
if decision.use_reasoning:
    if not capability_reasoning_enabled(decision.capability):
        decision = replace(decision, use_reasoning=False)
```

### 5.4. `app/admin_ui.py` — UI controls

#### Reasoning-capable models registry (для JS)

```python
REASONING_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.4-pro", "o4-mini", "o3", "o3-mini"],
    "gemini": ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
    "deepseek": ["deepseek-reasoner"],
    "openrouter": [],  # На OpenRouter все залежить від конкретної моделі — розбираємо по імені
}
```

#### В секції capability (тільки для group="smart")

Після select моделі додаємо:

```html
<div class="reasoning-controls">
    <label>
        <input type="checkbox" name="CAPABILITY_{slug}_REASONING_ENABLED" 
               id="reasoning_{slug}" {checked} {disabled}>
        Reasoning (thinking mode)
    </label>
    <select name="CAPABILITY_{slug}_REASONING_EFFORT" 
            id="effort_{slug}" class="effort-select" {hidden}>
        <option value="low">Low</option>
        <option value="medium" selected>Medium</option>
        <option value="high">High</option>
    </select>
</div>
```

#### JavaScript: auto-enable/disable checkbox

```javascript
function updateReasoningAvailability(slug) {
    const provider = document.querySelector(`[name="CAPABILITY_${slug}_PROVIDER"]`).value;
    const model = document.querySelector(`[name="CAPABILITY_${slug}_MODEL"]`).value;
    const checkbox = document.getElementById(`reasoning_${slug}`);
    const effortSelect = document.getElementById(`effort_${slug}`);
    
    const canReason = isReasoningCapable(provider, model);
    checkbox.disabled = !canReason;
    if (!canReason) {
        checkbox.checked = false;
        effortSelect.style.display = 'none';
    }
    effortSelect.style.display = checkbox.checked ? '' : 'none';
}

function isReasoningCapable(provider, model) {
    const m = model.toLowerCase();
    switch(provider.toLowerCase()) {
        case 'openai': return m.includes('gpt-5') || m.includes('o1') || m.includes('o3') || m.includes('o4');
        case 'gemini': return m.includes('2.5') || m.includes('3.');
        case 'deepseek': return m.includes('reasoner');
        case 'openrouter': return m.includes('gpt-5') || m.includes('o1') || m.includes('o3') || m.includes('o4') || m.includes('2.5') || m.includes('3.') || m.includes('reasoner');
        default: return false;
    }
}
```

### 5.5. Cleanup

**Видалити з `core/env.py`:** `reasoning_model()`, `reasoning_effort()` (глобальний), `provider_supports_reasoning()`

**Видалити з `.env` на сервері:** `OPENAI_REASONING_MODEL`, `OPENAI_REASONING_EFFORT`, `PROVIDER_*_SUPPORTS_REASONING`

**Видалити з `agent/llm.py`:** старий `_pick_model()` logic з `reasoning_model()`, старий `_maybe_reasoning_args()` з `reasoning_model()` check

## 6. Послідовність імплементації

1. `core/env.py` — додати `can_reason()`, `capability_reasoning_enabled()`, `capability_reasoning_effort()`
2. `agent/llm.py` — переписати `_maybe_reasoning_args()`, `_pick_model()`, `chat_once()`, Gemini path
3. `agent/planner.py` — розширити `_needs_reasoning()`, додати gate check
4. `app/admin_ui.py` — checkbox + effort select + JS validation
5. Cleanup старих функцій в `env.py` і `llm.py`
6. Тести: py_compile всіх файлів
7. Деплой + конфігурація на сервері (увімкнути reasoning для chat_final)
8. Девлог

## 7. Перевірка

1. **UI: checkbox сірий** для gpt-4.1, gpt-4.1-mini (не підтримують reasoning)
2. **UI: checkbox активний** для gpt-5.4-mini, o4-mini, gemini-2.5-pro, gemini-3.1-pro-preview
3. **Reasoning OFF, звичайне повідомлення** — запит без reasoning параметрів, з temperature
4. **Reasoning ON, звичайне повідомлення** — запит все ще без reasoning (effort=none), з temperature. Reasoning не активується без trigger.
5. **Reasoning ON + "подумай"** — запит з reasoning.effort=medium, без temperature
6. **Reasoning ON + `/think`** — те саме
7. **Gemini ON + trigger** — thinkingLevel/thinkingBudget відповідає effort
8. **Gemini OFF** — thinkingBudget=0 або thinkingLevel="minimal"
9. **DeepSeek + trigger** — модель замінюється на deepseek-reasoner
