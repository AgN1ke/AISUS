# Ландшафт Провайдерів

Огляд актуальний на 2026-04-04. Оновлено з конкретними моделями, цінами за 1M токенів, контекстними вікнами, capability maps і бенчмарками Chatbot Arena.

---

## Зміст

1. [Правило Читання](#правило-читання)
2. [OpenAI](#openai)
3. [Anthropic](#anthropic)
4. [Google Gemini](#google-gemini)
5. [DeepSeek](#deepseek)
6. [xAI / Grok](#xai--grok)
7. [Mistral](#mistral)
8. [Meta / Llama](#meta--llama)
9. [Спеціалізовані Голосові Провайдери](#спеціалізовані-голосові-провайдери)
10. [Інші Релевантні Провайдери](#інші-релевантні-провайдери)
11. [Зведена Таблиця Цін](#зведена-таблиця-цін)
12. [Prompt Caching Порівняння](#prompt-caching-порівняння)
13. [Chatbot Arena Rankings](#chatbot-arena-rankings)
14. [Рекомендовані Ролі Для Smartest](#рекомендовані-ролі-для-smartest)
15. [Джерела](#джерела)

---

## Правило Читання

Цей документ фіксує провайдерів релевантних для задач Telegram-бота: текст, reasoning, tool use, search, image/audio/video understanding, агентні workflows. Жоден провайдер не є "рішенням на все".

---

## OpenAI

### Поточні Моделі

**GPT-5.x Series (Frontier):**

| Модель | Input/1M | Output/1M | Context | Capabilities |
|--------|----------|-----------|---------|--------------|
| GPT-5.4 Pro | $30.00 | $180.00 | 1.1M | Premium reasoning, computer use |
| **GPT-5.4** | **$2.50** | **$15.00** | **1.1M** | Flagship. Vision, tools, search. 33% fewer factual errors vs 5.2 |
| GPT-5.2 | $1.75 | $14.00 | 400K | Instant + Thinking modes |
| GPT-5.1 | $0.625 | $5.00 | 400K | Codex variant для agentic coding |
| GPT-5 | $1.25 | $10.00 | 400K | Original GPT-5 |
| GPT-5 Mini | $0.125 | $1.00 | 400K | Budget GPT-5 |
| **GPT-5 Nano** | **$0.05** | **$0.40** | **400K** | Ultra-cheap |

**GPT-4.1 Series (Long Context):**

| Модель | Input/1M | Output/1M | Context | Cached Input |
|--------|----------|-----------|---------|-------------|
| GPT-4.1 | $2.00 | $8.00 | 1M+ | 75% off |
| GPT-4.1 Mini | $0.20-0.40 | $0.80-1.60 | 1M+ | 75% off |
| **GPT-4.1 Nano** | **$0.05-0.10** | **$0.20-0.40** | **1M+** | 75% off |

**O-Series (Reasoning):**

| Модель | Input/1M | Output/1M | Context |
|--------|----------|-----------|---------|
| o3 | $2.00 | $8.00 | 200K |
| o4 Mini | $0.55-1.10 | $2.20-4.40 | 200K |
| o3 Mini | $0.50 | $2.00 | 200K |

**Спеціалізовані:** STT (gpt-4o-transcribe $0.006/min), TTS ($15/1M chars), Realtime (gpt-realtime-1.5).

### Responses API vs Chat Completions

- **Responses API** — рекомендований для нових проєктів. Built-in tools (web search, file search, code interpreter, computer use, remote MCPs). Кращий cache utilization (40-80% improvement). Future innovation тут.
- **Chat Completions** — fully supported, no deprecation. Fine для lightweight stateless chat.
- **Assistants API** — deprecated серпень 2025, sunset серпень 2026.

### Prompt Caching

GPT-5.x: 90% off. GPT-4.1: 75% off. GPT-4o/o-series: 50% off. Автоматичний, не потребує explicit cache write.

### Batch API

50% off всіх моделей. Async processing, results within 24 hours.

### Висновок Для Smartest

OpenAI — найбільш versatile провайдер. GPT-4.1 Nano ($0.05/1M) — ідеальний для planner/router. GPT-5.4 — strong final responder. o3/o4 Mini — reasoning. STT і TTS — solid baseline. Але search через built-in web search tool — не primary path для нас (потрібен більший контроль).

---

## Anthropic

### Поточні Моделі

| Модель | Input/1M | Output/1M | Cache Hit | Context |
|--------|----------|-----------|-----------|---------|
| **Claude Opus 4.6** | **$5.00** | **$25.00** | **$0.50 (90%)** | **1M** |
| Claude Opus 4.5 | $5.00 | $25.00 | $0.50 | 1M |
| Claude Opus 4.1 | $15.00 | $75.00 | $1.50 | 200K |
| **Claude Sonnet 4.6** | **$3.00** | **$15.00** | **$0.30 (90%)** | **1M** |
| Claude Sonnet 4.5 | $3.00 | $15.00 | $0.30 | 1M |
| **Claude Haiku 4.5** | **$1.00** | **$5.00** | **$0.10** | **200K** |
| Claude Haiku 3.5 | $0.80 | $4.00 | $0.08 | 200K |
| Claude Haiku 3 | $0.25 | $1.25 | $0.03 | 200K |

**Важливо:** Opus 4.6 at $5/$25 — це 67% reduction від Opus 4.1 ($15/$75) при значно кращих capabilities.

### Prompt Caching

- 5-min cache write: 1.25x base input. 1-hour cache write: 2x base input.
- **Cache hit: 0.1x base input (90% savings).**
- Pays for itself після одного cache read (5-min) або двох reads (1-hour).

### Extended Thinking

Available на всіх Claude 4.x. Opus 4.6 і Sonnet 4.6 використовують **adaptive thinking** — Claude динамічно вирішує when/how much to think. Thinking tokens білляться як output tokens. Minimum budget: 1,024 tokens.

### Server-Side Tools

| Tool | Ціна |
|------|------|
| Web search | $10/1,000 searches |
| Web fetch | Free (token costs only) |
| Code execution | 1,550 free hours/month, then $0.05/hr |
| Computer use | Token costs |
| Text editor, Bash | Token costs |

### Що Немає

**Немає audio API для developers.** Voice mode тільки в consumer app (ElevenLabs subcontract). Немає STT/TTS endpoints.

### Висновок Для Smartest

Anthropic — найсильніший для reasoning + tool orchestration. Opus 4.6 лідирує на Chatbot Arena coding (#1, 1561 Elo). Sonnet 4.6 — excellent balance quality/price для final responder. Haiku 4.5 — good для evaluation tasks. Але НЕ для voice pipeline.

---

## Google Gemini

### Поточні Моделі

**Gemini 3.x (Newest):**

| Модель | Input/1M | Output/1M | Free Tier |
|--------|----------|-----------|-----------|
| Gemini 3.1 Pro Preview | $2.00-4.00 | $12.00-18.00 | Ні |
| Gemini 3 Flash Preview | $0.50 | $3.00 | **Так** |
| Gemini 3.1 Flash-Lite Preview | $0.25 | $1.50 | **Так** |

**Gemini 2.5 (Stable):**

| Модель | Input/1M | Output/1M | Free Tier | Context |
|--------|----------|-----------|-----------|---------|
| **Gemini 2.5 Pro** | **$1.25** (<=200K) / $2.50 (>200K) | **$10.00** / $15.00 | **Так** | **1M** |
| **Gemini 2.5 Flash** | **$0.30** | **$2.50** | **Так** | **1M** |
| **Gemini 2.5 Flash-Lite** | **$0.10** | **$0.40** | **Так** | **1M** |

### Multimodal Capabilities

**Всі моделі підтримують:** text, code, image, audio і video input natively.

Додатково:
- Image generation: Gemini Flash Image models.
- Video generation: Veo 3.1 ($0.05-$0.60/sec).
- TTS: Gemini TTS models ($10-20/1M output tokens).
- Live audio: Gemini Flash Live Preview (bidirectional voice+video).
- Computer Use: Preview model.
- Deep Research: Preview model.

### Grounding з Google Search

- 1,500 free grounded requests/day для Gemini 2.5 Pro.
- Потім $14-35 per 1,000 requests.

### Free Tier

- **Найщедріший free tier серед усіх провайдерів.**
- Gemini 2.5 Flash: 10 RPM, 500 RPD, 250K tokens/min.
- Rate limits знижені 50-80% в грудні 2025 через abuse.

### Context Caching

- Cache hit: 0.1x base input rate.
- Storage: $1.00-4.50/hour.

### Висновок Для Smartest

Gemini — **найкращий для multimodal** (image, video, audio). Flash-Lite at $0.10/1M — найдешевший capable model для planner/router. 2.5 Pro — єдиний нормальний варіант для video understanding. Free tier — ідеальний для development і testing. Google Search grounding — ready-made search fallback.

---

## DeepSeek

### Поточні Моделі

| Модель | Input/1M | Output/1M | Context | Тип |
|--------|----------|-----------|---------|-----|
| **DeepSeek V4** (березень 2026) | **$0.30** | **$0.50** | **1M** | General + multimodal |
| **DeepSeek R1** | $0.70 | $2.50 | 64K | Reasoning (chain-of-thought) |
| DeepSeek V3.2 | $0.28 | $0.42 | 128K | General purpose |

### Ключові Деталі

- **V4:** ~1 trillion parameter MoE, ~37B active per token. Перший DeepSeek з native multimodal (text, image, video). 81% на SWE-bench Verified. Hybrid reasoning modes.
- **R1:** спеціалізований reasoning model. Excellent math, logic, multi-step.
- **API Compatibility:** OpenAI-compatible. Але відмінності в tool calling, structured outputs, error semantics.
- **Off-Peak Discounts:** до 75% off для R1, 50% off для V3 (16:30-00:30 GMT).
- **Cache:** cached input $0.03/1M (90% discount).

### Limitations

- **Censorship:** вбудована на рівні training per Chinese government regulations. Відмовляє на politically sensitive topics. Running locally НЕ bypasses censorship — baked into model weights.
- **Reliability:** API має significant outages і capacity issues.
- **V4 Multimodal:** unverified — no published benchmarks для image/video quality.
- **Export Controls:** US export controls можуть обмежити доступ.

### Висновок Для Smartest

DeepSeek — **найдешевший text/reasoning provider** ($0.30/$0.50). R1 — сильний reasoning за low cost. Але: censorship issues, reliability concerns, unverified multimodal quality. Використовувати як **budget text executor і cheap reasoning fallback**, не як primary provider для user-facing responses.

---

## xAI / Grok

### Поточні Моделі

| Модель | Input/1M | Output/1M | Context |
|--------|----------|-----------|---------|
| **Grok 4.20** (flagship) | $2.00 | $6.00 | **2M** |
| Grok 4.1 Fast (reasoning) | $0.20 | $0.50 | 2M |
| Grok 4.1 Fast (non-reasoning) | $0.20 | $0.50 | 2M |
| Grok 4.20 Multi-Agent | $2.00 | $6.00 | 2M |

### Capabilities

- **Найбільший context window:** 2M tokens across all models.
- Vision: image input на всіх Grok 4 models.
- Built-in tools ($5/1,000 calls each): Web Search, X (Twitter) Search, Code Execution, Document Search.
- Image Generation: $0.02-0.07/image.
- Voice Agent API: $0.05/min ($3.00/hr).
- TTS: $4.20/1M chars.
- **X Integration:** real-time data з X/Twitter — unique competitive advantage.

### Free Credits

$25 free на signup + $150/month через data sharing program.

### Висновок Для Smartest

xAI цікавий через: 2M context window, X/Twitter integration, cheap fast model ($0.20/$0.50). Використовувати як **secondary provider для text + real-time social context**. Не primary через менш mature ecosystem.

---

## Mistral

### Ключові Моделі

| Модель | Input/1M | Output/1M | Context | Особливості |
|--------|----------|-----------|---------|-------------|
| **Mistral Large 3 (2512)** | **$0.50** | **$1.50** | 262K | Flagship, 675B/41B active MoE |
| Mistral Medium 3.1 | $0.40 | $2.00 | 131K | Advanced reasoning |
| **Mistral Small 4** | ~$0.15 | ~$0.60 | 128K+ | 119B/6B active. Reasoning + vision |
| Mistral Small 3.2 24B | $0.075 | $0.20 | 131K | Dense, vision |
| Codestral 2508 | $0.30 | $0.90 | 256K | Code specialist |
| Pixtral Large 2411 | $2.00 | $6.00 | 131K | Vision + language flagship |
| Pixtral 12B | $0.10 | $0.10 | 128K | Budget vision |
| Voxtral Small 24B | $0.10 | $0.30 | 32K | TTS, 9 мов |
| Ministral 3B/8B/14B | $0.04-0.20 | $0.04-0.20 | 128-262K | Edge/mobile |

### Ключові Переваги

- **European hosting:** GDPR-compliant EU data residency.
- **Open-weight models:** Hugging Face для self-hosting.
- **Vision everywhere:** Mistral 3 family brings vision до кожного tier.
- **Price leader:** Large 3 output $1.50/1M — 40% cheaper ніж GPT-5 output ($10.00).
- **Ministral 14B reasoning:** 85% на AIME 2025.

### Висновок Для Smartest

Mistral — excellent **budget production option**. Large 3 at $0.50/$1.50 з 262K context — дуже competitive. Корисний як: EU-compliant fallback, budget text model, self-hosting option. Не primary через менший ecosystem і обмежений multimodal (немає audio/video).

---

## Meta / Llama

### Llama 4 Family

| Модель | Тип | Context | Status |
|--------|-----|---------|--------|
| **Llama 4 Scout** | Compact | **10M tokens** | Open-weight |
| **Llama 4 Maverick** | Mid-range multimodal | — | Open-weight |
| Llama 4 Behemoth | Large-scale | — | Not fully available |

- Всі варіанти: text, image, video input natively.
- 200+ мов (10x більше multilingual tokens ніж Llama 3).
- Licensed: Llama Community License (не OSI-approved; 700M+ MAU потребують окрему ліцензію).

### Self-Hosting Economics

- **API через hosted providers (Groq, Together, Fireworks):** $0.05-0.90/1M tokens.
- **Self-hosting на cloud A100s (70B model):** ~$3,000-5,000/month, ~$0.07/1M at full utilization.
- **При 30% utilization (typical):** effective cost ~$0.23/1M — **не дешевше ніж API providers.**
- **Hidden costs:** 1-2 тижні engineering per major model update, $40K-100K/year maintenance.
- **Break-even:** ~100M+ tokens/month зі steady workloads.
- **Рекомендація:** hybrid — self-host small model (7-14B) для high-volume simple tasks, API для complex.

### Висновок Для Smartest

Llama цікавий якщо вирішимо self-host для зменшення залежності від API. Поки що для Smartest — **не потрібен**. API providers дешевші при нашому volume.

---

## Спеціалізовані Голосові Провайдери

### ElevenLabs

- **STT:** Scribe v2 ($0.22/hr) — **найкращий WER (3.5%), найкращий Ukrainian (3.1%).**
- **TTS:** Flash v2.5 (75ms, $60/1M chars), Multilingual v2 (highest quality, $120/1M chars), Eleven v3 (most expressive).
- **Voice cloning:** instant з short sample.
- **Conversational AI:** від $0.10/min — найдешевший realtime voice.
- Мови: 70+ включаючи українську.

### Deepgram

- **STT:** Nova-3 (~$0.47/hr streaming) — 300ms latency, 30% lower WER ніж Whisper на noisy audio.
- **TTS:** Aura-2 ($30/1M chars) — enterprise-grade, sub-200ms TTFB.
- **Мови STT:** 45+ включаючи українську.
- **Мови TTS:** 7 — **НЕМАЄ української.**
- Free tier: $200 credit.

### Cartesia

- **TTS:** Sonic Turbo — **40ms TTFB, найшвидший на ринку.**
- Мови: 15+, українська не підтверджена.
- Voice cloning з 3 секунд audio.

---

## Інші Релевантні Провайдери

### Inference Speed Providers

| Провайдер | Speed (TPS) | Latency | Спеціалізація |
|-----------|------------|---------|---------------|
| **Groq** | ~456 TPS | 0.19s | Custom LPU hardware, speed specialist |
| **Together AI** | ~917 TPS | 0.78s | Balance speed + reliability |
| **Fireworks AI** | ~747 TPS | 0.17s | Fastest multimodal, optimized structured output |

Всі offer open-source models (Llama, Mistral) at competitive per-token rates.

### Cohere (RAG Specialist)

| Модель | Input/1M | Output/1M |
|--------|----------|-----------|
| Command R+ | $2.50 | $10.00 |
| Command R | $0.15 | $0.60 |
| Embed v3 | $0.10 | — |
| Rerank 3.5 | $2/1,000 searches | — |

Embed v3 + Rerank 3.5 — best-in-class для RAG pipelines. Excellent multilingual support.

### Amazon Bedrock

- Marketplace 100+ models від Anthropic, Meta, Mistral, Amazon.
- Same per-token pricing як direct providers.
- 50% batch inference discount.
- Value: unified billing, VPC integration, guardrails, single API.

### Azure OpenAI

- **Identical base token pricing** як direct OpenAI API.
- **Total cost 15-40% higher** через support plans, data transfer, storage.
- Value: VNet integration, private endpoints, managed identity, content filtering, regional data residency, SLA-backed support.

---

## Зведена Таблиця Цін

### Flagship Models (per 1M tokens)

| Провайдер / Модель | Input | Output | Cache Hit | Batch Input | Context |
|---------------------|-------|--------|-----------|-------------|---------|
| **DeepSeek V4** | **$0.30** | **$0.50** | $0.03 (90%) | — | 1M |
| **Mistral Large 3** | **$0.50** | **$1.50** | — | — | 262K |
| Gemini 2.5 Pro | $1.25 | $10.00 | $0.125 (90%) | — | 1M |
| xAI Grok 4.20 | $2.00 | $6.00 | $0.20 (90%) | $1.00 | 2M |
| OpenAI GPT-4.1 | $2.00 | $8.00 | $0.50 (75%) | $1.00 | 1M+ |
| OpenAI GPT-5.4 | $2.50 | $15.00 | $0.25 (90%) | $1.25 | 1.1M |
| Anthropic Sonnet 4.6 | $3.00 | $15.00 | $0.30 (90%) | $1.50 | 1M |
| Anthropic Opus 4.6 | $5.00 | $25.00 | $0.50 (90%) | $2.50 | 1M |

### Budget / Fast Models (per 1M tokens)

| Провайдер / Модель | Input | Output | Context |
|---------------------|-------|--------|---------|
| **OpenAI GPT-4.1 Nano** | **$0.05** | **$0.20** | **1M+** |
| **OpenAI GPT-5 Nano** | **$0.05** | **$0.40** | 400K |
| **Gemini 2.5 Flash-Lite** | **$0.10** | **$0.40** | **1M** |
| OpenAI GPT-5 Mini | $0.125 | $1.00 | 400K |
| Mistral Small 3.2 | $0.075 | $0.20 | 131K |
| xAI Grok 4.1 Fast | $0.20 | $0.50 | 2M |
| Gemini 2.5 Flash | $0.30 | $2.50 | 1M |
| DeepSeek V3.2 | $0.28 | $0.42 | 128K |
| OpenAI o4 Mini | $0.55 | $2.20 | 200K |
| Anthropic Haiku 4.5 | $1.00 | $5.00 | 200K |

---

## Prompt Caching Порівняння

| Провайдер | Cache Hit Discount | Cache Write Cost | Duration |
|-----------|-------------------|------------------|----------|
| **Anthropic** | 90% off | 1.25x (5-min) або 2x (1-hour) | 5 хв або 1 год |
| **OpenAI (GPT-5.x)** | 90% off | Automatic | Automatic |
| **OpenAI (GPT-4.1)** | 75% off | Automatic | Automatic |
| **OpenAI (GPT-4o, o-series)** | 50% off | Automatic | Automatic |
| **Google Gemini** | 90% off | Standard rate | $1-4.50/hour storage |
| **DeepSeek** | 90% off | Standard rate | Automatic |

---

## Chatbot Arena Rankings

Rankings (березень 2026, 6M+ votes):

- **#1 General:** Gemini 3 Pro і Claude 4.6 / GPT-5.2 в statistical dead heat (~1492 Elo).
- **#1 Coding:** Claude Opus 4.6 (1561 Elo).
- **#1 Vision/Multimodal:** Gemini 3 (81% MMMU-Pro).

---

## Рекомендовані Ролі Для Smartest

### Capability → Provider Mapping

| Capability | Primary | Budget | Premium |
|------------|---------|--------|---------|
| **Planner / router** | GPT-4.1 Nano ($0.05/$0.20) | Gemini Flash-Lite ($0.10/$0.40) | — |
| **Final text responder** | Gemini 2.5 Flash ($0.30/$2.50) | GPT-4.1 Mini ($0.20/$0.80) | Sonnet 4.6 ($3/$15) |
| **Heavy reasoning** | o3 ($2/$8) | o4 Mini ($0.55/$2.20) | Opus 4.6 ($5/$25) |
| **Image understanding** | Gemini 2.5 Flash ($0.30) | Gemini Flash-Lite ($0.10) | Sonnet 4.6 ($3) |
| **Video understanding** | Gemini 2.5 Pro ($1.25) | Gemini 2.5 Flash ($0.30) | — |
| **STT** | OpenAI mini-transcribe ($0.18/hr) | AssemblyAI ($0.15/hr) | ElevenLabs Scribe ($0.22/hr) |
| **TTS** | OpenAI tts-1 ($15/1M chars) | Google Standard ($4/1M) | ElevenLabs ($60/1M) |
| **TTS Ukrainian** | Google Cloud ($4-16/1M) | — | ElevenLabs ($60-120/1M) |
| **Search orchestration** | Brave Search API ($5-9/1K) | Serper ($0.30-1/1K) | Exa ($1.50/1K) |
| **Memory summarization** | GPT-4.1 Nano ($0.05/$0.20) | Gemini Flash-Lite ($0.10/$0.40) | — |

### Рекомендована Архітектура Multi-Provider

```
User Message → Router (GPT-4.1 Nano / Gemini Flash-Lite)
                 │
                 ├─→ Chat: Gemini 2.5 Flash або GPT-4.1 Mini
                 ├─→ Reasoning: o3 або Opus 4.6
                 ├─→ Vision: Gemini 2.5 Flash
                 ├─→ Video: Gemini 2.5 Pro
                 ├─→ Search: Brave + Exa + Tavily (explicit pipeline)
                 ├─→ STT: OpenAI mini-transcribe
                 ├─→ TTS: OpenAI tts-1 / Google Cloud
                 └─→ Summarization: GPT-4.1 Nano (batch)
```

~80% requests → cheap, fast models ($0.05-0.30/1M). Expensive models тільки для complex reasoning або premium features.

### Стратегічні Висновки

1. **Архітектуру будувати навколо capability routing**, не навколо "улюбленої моделі".
2. **GPT-4.1 Nano і Gemini Flash-Lite** — два найдешевших capable models для planner/router/summarization. При $0.05-0.10/1M input — практично безкоштовно.
3. **Gemini — найсильніший для multimodal** (vision, video, audio). Free tier ідеальний для development.
4. **Claude Opus 4.6 — найсильніший для coding і complex reasoning**, але дорогий. Використовувати тільки де потрібна premium якість.
5. **DeepSeek — найдешевший text provider**, але censorship і reliability concerns. Budget fallback, не primary.
6. **Mistral Large 3 — hidden gem** при $0.50/$1.50 з 262K context. EU-compliant. Дуже competitive для production workloads.
7. **Voice pipeline — окремий capability layer.** Claude не має audio API. Використовувати OpenAI (STT/TTS baseline) + ElevenLabs (quality) + Google Cloud (Ukrainian TTS).
8. **Prompt caching — найвищий ROI optimization.** Anthropic 90%, OpenAI 90% (GPT-5.x), Gemini 90%. Використовувати для system prompts і repeated prefixes.

---

## Джерела

### Pricing і Models

- OpenAI Pricing: https://openai.com/api/pricing/
- OpenAI Models (PricePerToken): https://pricepertoken.com/pricing-page/provider/openai
- OpenAI Pricing Guide 2026: https://curlscape.com/blog/openai-api-pricing-guide-2026
- GPT-5.4 Announcement: https://openai.com/index/introducing-gpt-5-4/
- GPT-5.2 Announcement: https://openai.com/index/introducing-gpt-5-2/
- Responses API vs Chat Completions: https://platform.openai.com/docs/guides/responses-vs-chat-completions
- Anthropic Pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Claude Extended Thinking: https://platform.claude.com/docs/en/build-with-claude/extended-thinking
- Claude Pricing 2026 (Finout): https://www.finout.io/blog/claude-pricing-in-2026-for-individuals-organizations-and-developers
- Gemini Pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini Models: https://ai.google.dev/gemini-api/docs/models
- Gemini Rate Limits: https://ai.google.dev/gemini-api/docs/rate-limits
- DeepSeek Pricing: https://api-docs.deepseek.com/quick_start/pricing
- DeepSeek V4 Specs: https://www.nxcode.io/resources/news/deepseek-v4-release-specs-benchmarks-2026
- DeepSeek Censorship: https://www.promptfoo.dev/blog/deepseek-censorship/
- xAI Grok Models: https://docs.x.ai/developers/models
- Grok 4: https://x.ai/news/grok-4
- Mistral Models: https://mistral.ai/models
- Mistral Pricing (PricePerToken): https://pricepertoken.com/pricing-page/provider/mistral-ai
- Mistral Small 4: https://mistral.ai/news/mistral-small-4
- Llama 4: https://ai.meta.com/blog/llama-4-multimodal-intelligence/
- Self-Hosting vs API 2026: https://devtk.ai/en/blog/self-hosting-llm-vs-api-cost-2026/
- Cohere Pricing: https://www.metacto.com/blogs/cohere-pricing-explained-a-deep-dive-into-integration-development-costs
- Amazon Bedrock Pricing: https://aws.amazon.com/bedrock/pricing/
- Azure OpenAI Pricing: https://azure.microsoft.com/en-us/pricing/details/azure-openai/
- Azure OpenAI Hidden Costs: https://inference.net/content/azure-openai-pricing-explained/
- LLM Pricing Comparison 2026: https://www.cloudidr.com/blog/llm-pricing-comparison-2026
- PricePerToken: https://pricepertoken.com/

### Benchmarks

- Chatbot Arena Leaderboard: https://lmarena.ai/
- LMSYS Rankings March 2026: https://agileleadershipdayindia.org/blogs/lmsys-chatbot-arena-rankings/lmsys-chatbot-arena-rankings.html
