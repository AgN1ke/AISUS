# Схема Розділення Провайдерів

Оновлено: 2026-04-04. Перероблено з урахуванням актуальних цін і бенчмарків (`docs/research/provider-landscape.md`).

## Принцип

Провайдери ≠ capabilities. `chat_final` може працювати на Gemini Flash. `search_web` — на Brave API. `vision_image` — на Gemini. `stt_voice` — на OpenAI. Прив'язка — явна, per-capability.

## Дворівнева Конфігурація

### Рівень 1: Секрети (`.env`)

Тільки ключі і base URLs:

```env
PROVIDER_OPENAI_API_KEY=
PROVIDER_GEMINI_API_KEY=
PROVIDER_ANTHROPIC_API_KEY=
PROVIDER_DEEPSEEK_API_KEY=
PROVIDER_BRAVE_API_KEY=
PROVIDER_TAVILY_API_KEY=
PROVIDER_EXA_API_KEY=
PROVIDER_SERPER_API_KEY=
PROVIDER_ELEVENLABS_API_KEY=
```

### Рівень 2: Capability Routing

Прив'язка capability → provider/model/adapter. Зараз через env (`CAPABILITY_<NAME>_*`), потім через `config/capabilities.yaml` і admin UI.

## Capability Bindings

### 1. `chat_final` — Текстова Відповідь

| Роль | Provider | Model | Ціна/1M input |
|------|----------|-------|---------------|
| Primary | Gemini | gemini-2.5-flash | $0.30 |
| Alternative | OpenAI | gpt-4.1-mini | $0.20 |
| Premium | Anthropic | claude-sonnet-4.6 | $3.00 |

Policy: не приймає рішення про пошук, не викликає tools. Тільки фінальна відповідь з готового evidence.

### 2. `planner_reasoning` — Планувальник

| Роль | Provider | Model | Ціна/1M input |
|------|----------|-------|---------------|
| Primary | OpenAI | gpt-4.1-nano | $0.05 |
| Alternative | Gemini | gemini-2.5-flash-lite | $0.10 |

Policy: повертає structured plan (JSON), не формує відповідь користувачу. Cheap model — 20x дешевший за capable model.

### 3. `search_web` — Веб-Пошук

| Роль | Provider | Ціна/1K queries |
|------|----------|-----------------|
| Primary (general/news) | Brave | $5-9 |
| Primary (docs/research) | Exa | $1.50 |
| Extract/Crawl | Tavily | $8 |
| Fallback | Serper | $0.30-1.00 |
| Grounded fallback | Gemini google_search | Free (1500/day) |

Policy: повертає evidence (NormalizedResult), не готову відповідь. Profile-based provider routing.

### 4. `fetch_extract` — Витяг Контенту

| Роль | Provider |
|------|----------|
| Primary | Tavily `/extract` з `chunks_per_source` |
| Fallback | Власний `fetch_page` (BeautifulSoup) |

Policy: запускається тільки коли evaluator вирішив що snippets недостатньо.

### 5. `vision_image` — Аналіз Зображень

| Роль | Provider | Model | Ціна/1M input |
|------|----------|-------|---------------|
| Primary | Gemini | gemini-2.5-flash | $0.30 |
| Alternative | OpenAI | gpt-4.1-mini | $0.20 |
| Premium | Anthropic | claude-sonnet-4.6 | $3.00 |

Gemini — #1 на MMMU-Pro (81%). Free tier для development.

### 6. `video_understanding` — Аналіз Відео

| Роль | Provider | Model | Ціна |
|------|----------|-------|------|
| Primary | Gemini | gemini-2.5-pro | $1.25/1M, ~$0.005/хв відео |
| Alternative | Gemini | gemini-2.5-flash | $0.30/1M |

**Gemini — єдиний provider з native video input.** OpenAI і Anthropic не мають.

### 7. `stt_voice` — Транскрипція

| Роль | Provider | Model | Ціна/год |
|------|----------|-------|----------|
| Primary | OpenAI | gpt-4o-mini-transcribe | $0.18 |
| Budget | AssemblyAI | universal-2 | $0.15 |
| Best Ukrainian | ElevenLabs | scribe-v2 | $0.22 (WER 3.1% uk) |

### 8. `tts_voice` — Озвучення

| Роль | Provider | Model | Ціна/1M chars |
|------|----------|-------|---------------|
| Primary | OpenAI | tts-1 | $15 |
| Budget | Google Cloud | standard | $4 |
| Ukrainian | Google Cloud | wavenet | $16 |
| Premium | ElevenLabs | flash-v2.5 | $60 (75ms latency) |

**Deepgram НЕ підтримує українську.** Для TTS Ukrainian — Google Cloud або ElevenLabs.

### 9. `memory_summary` — Компресія Пам'яті

| Роль | Provider | Model | Ціна/1M input |
|------|----------|-------|---------------|
| Primary | OpenAI | gpt-4.1-nano | $0.05 |
| Alternative | Gemini | gemini-2.5-flash-lite | $0.10 |

Summarization — solved task. Найдешевша capable model достатньо.

## Що Вже В Коді

- `core/provider_registry.py`: `ProviderBinding`, capability-level resolution.
- `core/env.py`: `CAPABILITY_<NAME>_PROVIDER/ADAPTER/MODEL`, `PROVIDER_<NAME>_API_KEY/BASE_URL`.
- `agent/llm.py`: binding по capability замість global client.
- Native Gemini adapter (`gemini_generate_content`) для tool-less capabilities.
- `PROVIDER_GEMINI_THINKING_BUDGET=0` для flash models (інакше thinking tokens з'їдають бюджет).

## Наступний Крок

1. Винести capability bindings у `config/capabilities.yaml`.
2. Admin UI → edit capability routing (не тільки `.env`).
3. Розширити native adapters після Gemini.
4. Перевести tool-capability (search execution) на окремий transport.
