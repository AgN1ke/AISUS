# Матриця Можливостей

Оновлено: 2026-04-04.

## Як Читати Статуси

- `працює базово` — реальна реалізація в canonical runtime, можна спертися.
- `працює частково` — шар існує, не відповідає цільовому контракту.
- `legacy-only` — тільки в старому шарі.
- `відсутнє` — потрібне продукту, не оформлене.

## Матриця

| Capability | Статус | Модулі | Primary Provider | Пріоритет |
|------------|--------|--------|-----------------|-----------|
| **Telegram ingress + session gate** | працює частково | `run.py`, `adapters/*`, `app/message_logic.py` | — | Критичний |
| **Текстова відповідь** | працює базово | `agent/runner.py`, `agent/llm.py` | Gemini Flash ($0.30) / GPT-4.1 Mini ($0.20) | Критичний |
| **Planner / router** | працює частково | `agent/planner.py` | GPT-4.1 Nano ($0.05) | Критичний |
| **Search execution** | працює частково | `agent/runner.py`, `agent/search_task.py`, `agent/tools/web_search.py` | Brave ($5-9/1K) + Exa ($1.50/1K) | Критичний |
| **Image understanding** | працює частково | `media/router.py`, `media/vision.py` | Gemini Flash ($0.30, 81% MMMU-Pro) | Високий |
| **Voice STT** | працює частково | `media/router.py`, `whisper_tool.py` | OpenAI mini-transcribe ($0.18/hr) | Високий |
| **Voice TTS** | legacy-only | `src/voice_processor.py` | OpenAI tts-1 ($15/1M) / Google ($4/1M uk) | Високий |
| **Video understanding** | працює частково | `media/video.py`, `media/router.py` | Gemini Pro ($1.25/1M, ~$0.005/хв) | Високий |
| **Memory layer** | працює базово | `memory/manager.py`, `db/memory_repository.py` | GPT-4.1 Nano ($0.05) для summary | Високий |
| **Prompt governance** | працює частково | `core/prompts.py` | — | Високий |
| **Control plane** | мінімальний baseline | `app/admin_ui.py`, `smartest.klawa.top` | — | Середній |

## По Кожній Capability

### Telegram Ingress + Session Gate

`UnifiedMessage` — мінімальний transport object. Ще не повна модель Telegram-події: немає повної geometry (reply target, mention target, media reference як окремі поля). Цільовий контракт → `TelegramEvent` з `routing-contract.md`.

**Що треба:** Етап 4 — Telegram event normalization.

### Текстова Відповідь

Працює через `process_message()` → `run_simple()` → OpenAI-compatible chat completion. Provider binding через `core/provider_registry.py` вже є.

**Що треба:** розбити `process_message()` (Блок 1 roadmap), переключити default на Gemini Flash або GPT-4.1 Mini.

### Planner / Router

`agent/planner.py` — heuristic short-circuit для очевидних cases (media, search keywords) + LLM fallback для неоднозначних. Capability-specific `planner_model()` через provider registry.

**Що треба:** переключити на GPT-4.1 Nano ($0.05/1M). Planner не повинен потрапляти в user context.

### Search Execution

`SearchTask` з mode/recency/preferred_domains. Query composer з dialogue context. Evaluator + retry loop (max 3). Multi-provider auto-selection. Gemini search як fallback.

**Що треба:** повний pipeline з decomposition, parallel search, NormalizedResult, smart evaluation, selective extract, synthesis isolation. Деталі — `implementation-roadmap.md`, блоки 2-8.

### Image Understanding

`media/downloader.py` → `media/router.py` → `media/vision.py` → vision model. Image summary додається в context.

**Що треба:** переключити на Gemini Flash (81% MMMU-Pro, free tier для dev). Виділити як формальний executor з typed input/output.

### Voice STT

`whisper_tool.py` — заглушка в production. В legacy є реальна реалізація.

**Що треба:** Етап 5. Підключити OpenAI gpt-4o-mini-transcribe як primary. ElevenLabs Scribe якщо Ukrainian quality — пріоритет (3.1% WER).

### Voice TTS

Тільки в legacy `src/voice_processor.py` (OpenAI speech). Не в canonical runtime.

**Що треба:** Етап 5. Перенести в canonical runtime. Google Cloud для Ukrainian ($4-16/1M chars). ElevenLabs для premium.

### Video Understanding

`media/video.py` — FFmpeg frame extraction + Whisper transcription. Працює але не через native video API.

**Що треба:** Етап 5. Переключити на Gemini native video (1h max, ~$0.005/хв). Gemini — **єдиний** з native video.

### Memory Layer

Двохрівнева: recent (~10K tokens) + long (compressed summaries, ~30K). Auto-summarization при overflow. `memory/manager.py` + `memory/summarizer.py`.

**Що треба:** Етап 6. Memory summarization → GPT-4.1 Nano ($0.05/1M). Адаптація з `chibigochi`.

### Prompt Governance

Промпти централізовані в `core/prompts.py`. Persona prompt з env.

**Що треба:** сегментація по ролях (system, behavior, search, media, admin).

### Control Plane

Мінімальний admin UI: `smartest.klawa.top`, env editor, service restart.

**Що треба:** Етап 7. Після стабілізації capability bindings — edit routing через UI, не env.
