# Routing Contract

Оновлено: 2026-04-04.

## Проблема

`process_message()` в `app/message_logic.py` (~210 рядків) одночасно: auth, mentions, media routing, memory, agent decision, final response, Telegram send. Один метод = всі 10 шарів злиті.

## Цільовий Потік

```
1. Adapter           → сире оновлення платформи
2. Event Normalizer  → TelegramEvent
3. Access Gate       → auth, session state
4. Task Builder      → UserTask
5. Planner           → ExecutionPlan
6. Capability Router → executor(s)
7. Evaluator         → quality gate
8. Final Responder   → FinalResponse
9. Memory Layer      → зберігає контекст
10. Adapter          → outbound action
```

**Правило:** тільки Final Responder формує відповідь користувачу.

## Об'єкти Контракту

### TelegramEvent

Розширення `UnifiedMessage`:

- platform, chat_id, message_id, author
- chat type (private/group/supergroup)
- text, caption
- reply target (message_id, author, media type)
- mention target
- attachment type, media references
- is_instruction_on_target (reply-to-media + text prompt)

### SessionState

- auth state, mode
- memory context
- model overrides, feature flags
- temporary policy decisions

### UserTask

- instruction (text)
- has_media_target, media_type, media_context
- needs_search_hint (heuristic)
- target_message reference

### ExecutionPlan

Planner повертає plan, не відповідь:

- capability steps (ordered)
- evaluator needed?
- retry allowed?
- who builds final response?

Приклади:
- text question → `chat_final`
- tagged image + instruction → `vision_image` → `final_responder`
- factual news question → `search_web` → `evaluator` → `final_responder`
- voice input → `stt_voice` → `planner` → route далі

**ExecutionPlan і control-plane артефакти НЕ йдуть в memory і НЕ в prompt final model.**

### SearchTask / SearchPlan

Якщо plan включає search:

- `SearchPlan`: sub_queries (1-3), profiles, alternatives
- `SearchTask`: query, mode, recency, domains, max_iterations

Query composer будує — не planner і не search provider.

### CapabilityRequest / CapabilityResult

Стандартизований вхід/вихід для кожного executor:

Request: capability name, normalized input, task hint, session slice, policy, budget/timeout.

Result: capability name, structured payload, confidence/quality hints, provenance/sources, error state.

### FinalResponse

Не просто text. Outbound action:

- text reply, voice reply, media reply
- citations
- meta flags для memory/logging

## Відповідальність Шарів

| Шар | Робить | НЕ робить |
|-----|--------|-----------|
| **Adapter** | Отримує сире оновлення, віддає в normalizer | Не вирішує чи це мем чи пошук |
| **Event Normalizer** | Перетворює PTB/Telethon в TelegramEvent | Не генерує відповіді |
| **Access Gate** | Auth, session state, може повернути deny | Не media routing |
| **Planner** | Визначає route, capability steps | Не виконує search/vision/etc |
| **Executors** | Search, fetch, STT, vision, video, TTS | Не відправляють в Telegram |
| **Evaluator** | Quality gate: достатньо? retry? switch capability? | Не генерує content |
| **Final Responder** | Human-readable відповідь з evidence | Не planner, не executor |
| **Memory** | Зберігає context, compresses history | Не маршрутизатор |

## Mapping Поточного Коду

| Цільовий шар | Поточний код | Статус |
|--------------|-------------|--------|
| Adapter | `adapters/*` | Працює |
| Event Normalizer | `UnifiedMessage` | Мінімальний, не повний TelegramEvent |
| Access Gate | Частина `process_message()` | Не виділено |
| Task Builder | Частина `process_message()` | Не виділено |
| Planner | `agent/planner.py` | Працює, потрібен cheaper model |
| Executors | `agent/runner.py`, `media/*` | Змішані з synthesis |
| Evaluator | `agent/search_task.py` | Базовий, потрібен per-sub-query coverage |
| Final Responder | Частина `agent/runner.py` | Не ізольований |
| Memory | `memory/manager.py` | Працює базово |

**Перший крок:** Блок 1 з `implementation-roadmap.md` — розрізати `process_message()` по цих межах.
