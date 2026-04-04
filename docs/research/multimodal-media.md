# Мультимодальний І Голосовий Стек

Огляд актуальний на 2026-04-04. Оновлено з конкретними моделями, цінами, latency, бенчмарками і порівняннями на основі офіційних docs і pricing pages провайдерів.

---

## Зміст

1. [Розуміння Зображень](#розуміння-зображень)
2. [Speech-to-Text (STT)](#speech-to-text-stt)
3. [Text-to-Speech (TTS)](#text-to-speech-tts)
4. [Розуміння Відео](#розуміння-відео)
5. [Голос У Реальному Часі](#голос-у-реальному-часі)
6. [Розуміння Документів](#розуміння-документів)
7. [Нові Гравці І Зміни](#нові-гравці-і-зміни)
8. [Рекомендації Для Smartest](#рекомендації-для-smartest)
9. [Джерела](#джерела)

---

## Розуміння Зображень

### OpenAI

- **Моделі:** GPT-5.4, GPT-5.4-mini, GPT-5.4-nano, GPT-4.1, GPT-4.1 Mini, GPT-4.1 Nano — всі підтримують image input.
- **Формати:** JPEG, PNG, GIF, WebP.
- **Token calculation (high detail):** зображення масштабується до 2048x2048, коротша сторона до 768px, потім ділиться на 512px tiles. Кожен tile = 170 tokens + 85 base. 1024x1024 image = ~765 tokens. Low detail = fixed 85 tokens.
- **Множники:** gpt-4.1-mini множить image tokens на 1.62x; gpt-4.1-nano на 2.46x.
- **Ціна:** при GPT-5.4 ($2.50/1M input) — high-detail 1024x1024 = ~$0.0019. При GPT-4.1 — ~$0.0077.
- **Capabilities:** OCR, chart/graph reading, object identification, scene description, meme understanding, document analysis.
- **Limitations:** не ідентифікує обличчя по імені, spatial reasoning обмежений, approximate counting.

### Google Gemini

- **Моделі:** Gemini 2.5 Pro ($1.25/1M), Gemini 2.5 Flash ($0.30/1M), Gemini 2.5 Flash-Lite ($0.10/1M), Gemini 3.1 Pro Preview ($2.00/1M), Gemini 3.1 Flash-Lite Preview ($0.25/1M).
- **Context:** 1M tokens (2.5 Pro supports 2M).
- **Pricing:** images tokenized based on resolution, same per-token rate як text.
- **Benchmarks:** 81% на MMMU-Pro (Gemini 3), 72.7% на ScreenSpot-Pro. **Найсильніша multimodal модель overall.**
- **Free tier:** available для більшості models з rate limits.

### Anthropic Claude

- **Моделі:** Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 — всі підтримують vision.
- **Формати:** JPEG, PNG, GIF, WebP.
- **Size limits:** max 8000x8000 px; 5 MB per image (API), 10 MB (claude.ai). >20 images in batch → 2000x2000 limit.
- **Max images:** до 600 per API request (100 для 200K context models); 20 на claude.ai.
- **Token formula:** `tokens = (width × height) / 750`. 1092x1092 = ~1,590 tokens.
- **Ціна:** при Sonnet 4.6 ($3/1M input) — 1092x1092 = ~$0.0048 ($4.80 per 1,000 images).
- **Capabilities:** сильний OCR (especially з imperfect images), chart/graph interpretation, document layout, multi-image comparison.
- **Limitations:** не ідентифікує обличчя, spatial reasoning обмежений.

### xAI Grok

- **Моделі:** Grok 4.1 Fast ($0.20/1M), Grok 4.20 ($2.00/1M); vision на grok-2-vision-1212.
- **Context:** 2M tokens (найбільший у індустрії).
- **Capabilities:** базове image understanding, text extraction from screenshots.
- **Status:** vision capabilities значно відстають від GPT-5.4, Gemini і Claude.

### Зведена Таблиця Vision

| Провайдер | Найкраща модель для vision | Ціна/1M tokens | Benchmarks |
|-----------|--------------------------|----------------|------------|
| **Gemini** | 2.5 Pro / 3.1 Pro | $0.10-2.00 | 81% MMMU-Pro |
| **OpenAI** | GPT-5.4 | $2.50 | Strong baseline |
| **Anthropic** | Sonnet 4.6 | $3.00 | Strong OCR |
| **xAI** | Grok 4.20 | $2.00 | Basic |

---

## Speech-to-Text (STT)

### OpenAI

| Модель | Ціна/хв | Ціна/год | Особливості |
|--------|---------|----------|-------------|
| `whisper-1` | $0.006 | $0.36 | Legacy, 50+ мов |
| `gpt-4o-transcribe` | $0.006 | $0.36 | Покращена accuracy |
| `gpt-4o-mini-transcribe` | $0.003 | $0.18 | Найкраще value |
| `gpt-4o-transcribe-diarize` | $0.006 | $0.36 | Speaker diarization |

- File limit: 25 MB max.
- Формати: mp3, mp4, mpeg, mpga, m4a, wav, webm.
- Мови: 50+ включаючи українську.
- WER: Whisper large-v3 = 2.1% на clean English; high-resource мови 3-8%, medium-resource 8-15%.
- Billing: per duration uploaded file (including silence).

### ElevenLabs Scribe

| Модель | Ціна/год | Особливості |
|--------|----------|-------------|
| Scribe v2 | $0.22 | Batch processing |
| Scribe v2 Realtime | $0.39 | ~150ms latency |

- Мови: 99 включаючи українську.
- **Ukrainian WER: 3.1% на FLEURS, 5.5% на Common Voice** — classified as "excellent accuracy" (<5% WER).
- **Overall WER: ~3.5% aggregate — найнижчий серед усіх commercial STT.**
- Features: speaker diarization, word-level timestamps, audio event tagging.
- Released: січень 2026, accuracy leader.

### Deepgram

| Модель | Ціна/хв (PAYG) | Ціна/хв (Growth) | Особливості |
|--------|----------------|-------------------|-------------|
| Nova-3 Monolingual | $0.0077 | $0.0065 | English-optimized |
| Nova-3 Multilingual | $0.0092 | $0.0078 | 45+ мов |
| Nova-2 | $0.0058 | $0.0047 | Previous gen |
| Flux | $0.0077 | — | Newest |

- Add-ons: diarization +$0.0020/min, redaction +$0.0020/min.
- Мови: 45+ включаючи українську.
- WER: ~6.84% aggregate; 30% нижчий ніж Whisper на noisy/accented audio.
- Latency: ~300ms (P50) для real-time streaming.
- Free tier: $200 credit (~43,000 хвилин).

### AssemblyAI

- Модель: Universal-2.
- **Ціна: $0.15/год ($0.0025/хв) — найдешевший.**
- Add-ons: diarization +$0.02/hr, entity detection +$0.08/hr, summarization +$0.03/hr.
- Мови: 99 включаючи українську.
- Free tier: $50 credit (~185 годин).
- Features: real-time streaming, PII redaction, custom vocabularies.

### Google Cloud Speech-to-Text

- Моделі: Chirp 3 (latest), V2 API.
- Ціна: $0.016/хв standard; $0.004/хв dynamic batch (75% discount, results within 24h).
- Мови: 85+ включаючи українську.
- Free tier: 60 хвилин/місяць.

### Зведена Таблиця STT (ціна за годину)

| Провайдер | Модель | Ціна/год | Українська | WER |
|-----------|--------|----------|------------|-----|
| **AssemblyAI** | Universal-2 | **$0.15** | Так | Good |
| **OpenAI** | gpt-4o-mini-transcribe | $0.18 | Так | ~3-8% |
| **ElevenLabs** | Scribe v2 | $0.22 | Так (**3.1%**) | **~3.5%** |
| **Deepgram** | Nova-2 | $0.35 | Так | ~6.8% |
| **OpenAI** | gpt-4o-transcribe | $0.36 | Так | ~2-8% |
| **Deepgram** | Nova-3 Multi | $0.55 | Так | Better than Nova-2 |
| **Google** | Chirp 3 | $0.96 | Так | Good |

---

## Text-to-Speech (TTS)

### OpenAI

| Модель | Ціна/1M chars | Якість |
|--------|---------------|--------|
| `tts-1` | $15 | Standard |
| `tts-1-hd` | $30 | High definition |
| `gpt-4o-mini-tts` | $0.60/1M input + $12/1M audio output tokens | Instruction-following |

- Голоси: 13 built-in (alloy, ash, coral, echo, fable, onyx, nova, sage, shimmer, marin, cedar тощо).
- Формати: MP3, Opus, AAC, FLAC, WAV, PCM.
- Streaming: підтримується.
- Limitations: немає voice cloning, English-optimized.

### ElevenLabs

| Модель | Ціна/1K chars | Ціна/1M chars | Latency |
|--------|---------------|---------------|---------|
| Flash v2.5 | $0.06 | ~$60 | 75ms |
| Multilingual v2/v3 | $0.12 | ~$120 | Higher |
| Eleven v3 | — | — | Most expressive |

- Голоси: extensive library + custom voice cloning.
- Мови: 70+ включаючи **українську**.
- Voice cloning: instant clone з short sample; professional clone available.
- Capabilities: emotional/expressive control, laughter, breathing, accent preservation.
- **Найкраща якість голосу на ринку.**

### Deepgram

| Модель | Ціна/1K chars | Ціна/1M chars |
|--------|---------------|---------------|
| Aura-1 | $0.015 | $15 |
| Aura-2 | $0.030 | $30 |

- Мови: 7 (English, Spanish, Dutch, French, German, Italian, Japanese) — **НЕМАЄ української**.
- Голоси: 40+ professional English.
- Latency: Sub-200ms TTFB.
- Focus: enterprise use cases.

### Google Cloud TTS

| Модель | Ціна/1M chars |
|--------|---------------|
| Standard | $4 |
| WaveNet/Neural2 | $16 |
| Chirp 3 HD | $30 |

- Голоси: 380+ across 75+ мов.
- Мови: 75+ включаючи **українську**.
- Free tier: 1M WaveNet chars/month, 4M standard chars/month.
- SSML support, adjustable pitch/speed.

### Cartesia

| Модель | TTFB | Особливості |
|--------|------|-------------|
| Sonic 3 | ~90ms | Expressive |
| Sonic Turbo | **~40ms** | **Найшвидший на ринку** |

- Мови: 15+ (українська не підтверджена).
- Voice cloning: instant з 3 секунд audio; Pro clone available.
- Nonverbal: laughter, breathing, emotional inflections.

### Нові Гравці TTS

- **Qwen3-TTS (Alibaba):** open-source (Apache 2.0), 97ms latency, beats ElevenLabs на WER, voice cloning з 3 секунд. **Безкоштовно при self-hosting.**
- **Fish Audio:** $15/1M UTF-8 bytes (~12 годин speech), 50-70% дешевший за subscription alternatives. Emotion control tags, voice cloning з 3 секунд.
- **PlayHT:** 829 голосів, 142 мови.

### Зведена Таблиця TTS (ціна за 1M символів)

| Провайдер | Модель | Ціна/1M chars | Українська | Latency | Якість |
|-----------|--------|---------------|------------|---------|--------|
| **Google** | Standard | **$4** | Так | Medium | Basic |
| **Deepgram** | Aura-1 | $15 | Ні | <200ms | Good |
| **OpenAI** | tts-1 | $15 | Limited | Medium | Good |
| **Google** | WaveNet | $16 | Так | Medium | Good |
| **Deepgram** | Aura-2 | $30 | Ні | <200ms | Better |
| **Google** | Chirp 3 HD | $30 | Так | Medium | Very Good |
| **OpenAI** | tts-1-hd | $30 | Limited | Medium | Very Good |
| **ElevenLabs** | Flash v2.5 | $60 | Так | **75ms** | Excellent |
| **ElevenLabs** | Multilingual v2 | $120 | Так | Higher | **Best** |

---

## Розуміння Відео

### Google Gemini (Лідер Ринку)

- **Моделі:** Gemini 2.5 Pro, 2.5 Flash, 3.1 Pro Preview — всі підтримують video input.
- **Max length:** до 1 години при default resolution, 3 години при low resolution, ~6 годин з 2M context (Gemini 2.5 Pro low-res).
- **Processing:** sampled at 1 FPS за замовчуванням. Audio processed at 1Kbps mono.
- **Token consumption:**
  - Standard models: 258 tokens/frame + 32 tokens/second audio = ~300 tokens/sec default, ~100 tokens/sec low-res.
  - Gemini 3: 70 tokens/frame.
- **Capabilities:** scene description, temporal event analysis, OCR в відео, audio track analysis.
- **Ціна:** при Gemini 2.5 Flash ($0.30/1M tokens) — 1 хвилина відео = ~18,000 tokens = **~$0.005**.

### OpenAI

- **Status:** немає native video input в API.
- **Workaround:** extract frames + transcribe audio окремо, send як images + text.
- **Limitations:** втрата motion dynamics, високий token cost для довгих відео, manual preprocessing.

### Anthropic Claude

- **Status:** немає video input support.
- **Workaround:** frame extraction (до 600 images per request).

### xAI Grok

- **Status:** обмежений. Batch API підтримує video generation але understanding capabilities unclear.

**Висновок: Gemini — єдиний і безальтернативний лідер для native video understanding.**

---

## Голос У Реальному Часі

### OpenAI Realtime API

| Параметр | gpt-realtime-1.5 | gpt-realtime-mini |
|----------|-------------------|-------------------|
| Audio input | $32/1M tokens | $10/1M tokens |
| Audio output | $64/1M tokens | $20/1M tokens |
| Cached input | $0.40/1M | — |
| Text input | $4/1M | $0.60/1M |
| Text output | $16/1M | $2.40/1M |

- Effective cost: ~$0.06/хв audio input, ~$0.24/хв audio output (gpt-realtime-1.5).
- Архітектура: persistent WebSocket connection.
- Capabilities: natural speech з instruction-following, fine-grained context control.
- **Найзріліший realtime voice product.**

### Gemini Live API

- Моделі: gemini-live-2.5-flash-native-audio, gemini-3.1-flash-live.
- Ціна: $0.50/1M text input, $3.00/1M audio input, $12.00/1M audio output.
- Capabilities: 24 мови, barge-in, affective dialog, tool use, Google Search integration.
- Особливість: context window billing per turn (all accumulated tokens re-billed each turn).

### ElevenLabs Conversational AI

- Ціна: від $0.10/хв (березень 2026, ~50% reduction).
- Архітектура: з'єднує STT + LLM + TTS в одну сесію.
- Features: custom turn-taking model, RAG knowledge base, batch calling APIs, telephony/SIP.
- Мови: 70+.
- **Conversational AI 2.0 — найдешевший realtime voice.**

### Коли Realtime vs Async STT+TTS

| Realtime | Async STT+TTS |
|----------|---------------|
| Natural conversational flow | Cheaper processing |
| Barge-in support | Batch workloads |
| Emotional responsiveness | Specific model control |
| <500ms round-trip потрібен | Не потрібен real-time |

**Для Smartest (Telegram bot):** async STT+TTS достатньо. Realtime voice — тільки якщо з'явиться Telegram voice call integration.

---

## Розуміння Документів

### PDF Processing

| Провайдер | Метод | Precision | Recall | Strengths |
|-----------|-------|-----------|--------|-----------|
| **Claude** (Opus 4.6, Sonnet 4.6) | Renders pages as images + text | 90% | 80% | Complex layouts, tables, charts |
| **Gemini** (2.5 Pro, 3.1 Pro) | Native multimodal, 1M+ context | 93% | 81% | Massive documents (2M tokens) |
| **OpenAI** (GPT-5.4) | Files API + vision | 83% | 73% | Reliable structured JSON output |

- **OCR:** всі три добре; Claude excels на imperfect/rotated text.
- **Table extraction:** Claude і Gemini lead; OpenAI reliable для structured JSON.
- **Chart reading:** Claude Sonnet встановив benchmark; Gemini competitive.

---

## Нові Гравці І Зміни

### Major Releases (кінець 2025 — початок 2026)

- **OpenAI GPT-5.4** (flagship): $2.50/$15 per 1M tokens, замінив GPT-4o (deprecated лютий 2026).
- **Anthropic Claude Opus 4.6:** 1M token context window (лютий 2026).
- **Google Gemini 3.1 Pro/Flash-Lite Preview:** next-gen models.
- **ElevenLabs Scribe v2:** accuracy leader в STT (3.5% WER), excellent Ukrainian (3.1%).
- **Qwen3-TTS (Alibaba):** open-source, 97ms latency, voice cloning.

### Важлива Зміна: Claude Не Має Audio API

Claude **НЕ має** native audio input/output через API для developers. Voice mode існує тільки в consumer app (using ElevenLabs для TTS). **Немає developer-accessible STT/TTS endpoints.** Це означає що для voice capabilities в Smartest Claude не є кандидатом.

---

## Рекомендації Для Smartest

### Рекомендований Стек По Capabilities

| Capability | Primary | Budget Alternative | Premium |
|------------|---------|-------------------|---------|
| **Image understanding** | Gemini 2.5 Flash ($0.30/1M) | Gemini Flash-Lite ($0.10/1M) | Claude Sonnet 4.6 ($3/1M) |
| **STT** | OpenAI gpt-4o-mini-transcribe ($0.18/hr) | AssemblyAI ($0.15/hr) | ElevenLabs Scribe ($0.22/hr, найкращий Ukrainian) |
| **TTS** | OpenAI tts-1 ($15/1M chars) | Google Standard ($4/1M chars) | ElevenLabs Flash ($60/1M chars) |
| **TTS Ukrainian** | Google Cloud ($4-16/1M) | — | ElevenLabs ($60-120/1M) |
| **Video understanding** | Gemini 2.5 Pro ($1.25/1M) | Gemini 2.5 Flash ($0.30/1M) | — |
| **Realtime voice** | Не потрібен зараз | — | OpenAI Realtime / ElevenLabs Conv AI |
| **Document/PDF** | Gemini 2.5 Pro (1M context) | — | Claude Opus 4.6 (complex layouts) |

### Ключові Висновки Відносно Попереднього Дослідження

1. **Gemini піднято для vision:** бенчмарки 2026 показують що Gemini 3 найсильніша multimodal модель (81% MMMU-Pro). Раніше OpenAI був baseline — тепер Gemini.

2. **ElevenLabs Scribe — новий лідер STT:** 3.5% WER aggregate, 3.1% на українській. Раніше не існував. Тепер найкращий вибір якщо Ukrainian quality — пріоритет.

3. **AssemblyAI — найдешевший STT:** $0.15/год. Раніше не розглядався.

4. **Deepgram TTS не підтримує українську.** Тому для TTS Ukrainian вибір: Google Cloud або ElevenLabs.

5. **Cartesia Sonic Turbo — найшвидший TTS (40ms TTFB).** Раніше не існував.

6. **Claude не має audio API для developers.** Voice в consumer app через ElevenLabs subcontract. Для Smartest це означає Claude не кандидат для voice pipeline.

7. **Gemini залишається єдиним для video understanding.** Нічого не змінилось — OpenAI і Anthropic все ще не мають native video input.

### Продуктові Наслідки

1. Voice stack = окремий capability layer. Primary STT: OpenAI (cheapest capable) або ElevenLabs Scribe (best Ukrainian). Primary TTS: OpenAI (baseline) або Google Cloud (Ukrainian + cheap).
2. Video stack = Gemini. Не впихати в того самого провайдера що робить текст.
3. Image pipeline = Gemini Flash як default (cheap + strong), Claude для complex analysis.
4. Reply-to-media architecture через media target object: tagged message → media type → extracted content → user instruction → synthesis policy.

---

## Джерела

### Image Understanding

- OpenAI Vision: https://platform.openai.com/docs/guides/vision
- OpenAI API Pricing: https://developers.openai.com/api/docs/pricing
- Gemini Vision: https://ai.google.dev/gemini-api/docs/vision
- Gemini Pricing: https://ai.google.dev/gemini-api/docs/pricing
- Anthropic Vision: https://docs.anthropic.com/en/docs/build-with-claude/vision
- Anthropic Pricing: https://platform.claude.com/docs/en/about-claude/pricing
- xAI Image Understanding: https://docs.x.ai/docs/guides/image-understanding

### STT

- OpenAI Speech-to-Text: https://platform.openai.com/docs/guides/speech-to-text
- OpenAI Transcription Pricing: https://costgoat.com/pricing/openai-transcription
- ElevenLabs Scribe: https://elevenlabs.io/speech-to-text
- ElevenLabs Ukrainian STT: https://elevenlabs.io/speech-to-text/ukrainian
- Deepgram Pricing: https://deepgram.com/pricing
- Deepgram Best STT 2026: https://deepgram.com/learn/best-speech-to-text-apis-2026
- AssemblyAI Pricing: https://www.assemblyai.com/pricing
- Google Cloud STT Pricing: https://cloud.google.com/speech-to-text/pricing

### TTS

- OpenAI Text-to-Speech: https://platform.openai.com/docs/guides/text-to-speech
- ElevenLabs Pricing: https://elevenlabs.io/pricing
- Deepgram Aura-2: https://deepgram.com/learn/introducing-aura-2-enterprise-text-to-speech
- Google Cloud TTS Pricing: https://cloud.google.com/text-to-speech/pricing
- Cartesia Pricing: https://cartesia.ai/pricing
- Fish Audio TTS Comparison: https://fish.audio/blog/top-tts-apis-developer-comparison-2026/
- Speechmatics Best TTS 2026: https://www.speechmatics.com/company/articles-and-news/best-tts-apis-in-2025-top-12-text-to-speech-services-for-developers

### Video

- Gemini Video Understanding: https://ai.google.dev/gemini-api/docs/video-understanding

### Realtime Voice

- OpenAI Realtime API: https://openai.com/index/introducing-gpt-realtime/
- OpenAI Realtime Models: https://developers.openai.com/api/docs/models/gpt-realtime
- Gemini Live API: https://ai.google.dev/gemini-api/docs/live-api
- ElevenLabs Conversational AI: https://elevenlabs.io/conversational-ai

### Documents

- Anthropic PDF Support: https://docs.anthropic.com/en/docs/build-with-claude/pdf-support
- Multimodal AI Comparison: https://www.index.dev/blog/multimodal-ai-models-comparison
