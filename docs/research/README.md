# Дослідницька Бібліотека

Останній огляд: 2026-04-04

## Призначення

Ця папка фіксує перший шар актуалізації знань перед великою перебудовою бота.

Мета не в тому, щоб зібрати "все про все", а в тому, щоб:

- не будувати нову архітектуру на застарілих уявленнях;
- розділити ринок на capability-шари, а не на бренди;
- зафіксувати, які сучасні API та фреймворки реально релевантні для нашого бота;
- сформувати базову бібліотеку джерел для наступних ітерацій.

## Що Треба Тримати Актуальним

### 1. Оркестрація Та Агентивний Рантайм

Потрібно постійно актуалізувати:

- Responses / Messages / Live API підходи;
- multi-agent orchestration;
- tool calling;
- MCP / ACP / protocol-based integrations;
- tracing, sessions, guardrails, retries, evaluation.

### 2. Карта Можливостей Провайдерів

Потрібно знати не "яка модель хайпова", а:

- хто добре робить текст;
- хто добре робить reasoning;
- хто реально підтримує tool use;
- хто підтримує image understanding;
- хто підтримує audio in/out;
- хто підтримує video understanding;
- хто підходить лише як text executor.

### 3. Пошуковий Стек

Потрібно відділяти:

- raw search providers;
- grounded answer engines;
- search tools, які самі вирішують усе всередині моделі;
- керований search pipeline, який ми контролюємо самі.

### 4. Голосовий І Мультимодальний Стек

Потрібно окремо відстежувати:

- STT;
- TTS;
- realtime voice;
- image understanding;
- video understanding;
- reply-to-media workflows.

### 5. Операційні Патерни І Керувальний Контур

Потрібно мати сучасні референси для:

- керування ключами;
- model failover;
- auth/profile routing;
- feature flags;
- session overrides;
- control UI / dashboard.

## Карта Бібліотеки

- [provider-landscape.md](/C:/Python_projects/Smartest/docs/research/provider-landscape.md) — актуальний зріз провайдерів, моделей і capability-map.
- [agentic-architectures.md](/C:/Python_projects/Smartest/docs/research/agentic-architectures.md) — як сьогодні будують агентні системи, що брати, що не брати.
- [multimodal-media.md](/C:/Python_projects/Smartest/docs/research/multimodal-media.md) — image / audio / video / voice API landscape.
- [search-stack.md](/C:/Python_projects/Smartest/docs/research/search-stack.md) — окремий шар по пошуку, grounded responses і multi-step search.

## Робоче Правило

Це дослідницька база, а не остаточна істина.

Перед кожним великим архітектурним рішенням потрібно перевіряти:

- чи не змінилися моделі;
- чи не з'явився кращий API;
- чи не змінились capability limits;
- чи не з'явились нові інструменти, які знімають частину нашої майбутньої кастомної роботи.
