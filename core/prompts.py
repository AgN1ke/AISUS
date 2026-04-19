from __future__ import annotations

import os
import textwrap

from core.runtime_user_settings import current_runtime_user_settings
from core.user_preferences import persona_preset


def _block(text: str) -> str:
    return textwrap.dedent(text).strip()


def format_env_prompt(value: str | None, default: str = "") -> str:
    raw = value if value not in (None, "") else default
    return str(raw or "").replace(" | ", "\n").strip()


# Головний persona/system prompt бота. Використовується під час складання
# системного prompt-а для фінальної текстової відповіді та мультимодальних
# capability, якщо його задано через env.
CONFIGURED_CHAT_PERSONA_ENV = "SYSTEM_MESSAGES_GPT_PROMPT"


def configured_chat_persona_prompt() -> str:
    return format_env_prompt(os.getenv(CONFIGURED_CHAT_PERSONA_ENV), default="")


def current_persona_slug() -> str:
    settings = current_runtime_user_settings()
    return str(settings.get("persona_slug") or "").strip().lower()


def resolve_persona_for_user() -> str:
    base_persona = configured_chat_persona_prompt()
    override = persona_preset(current_persona_slug())
    override_prompt = (override.prompt if override else "").strip()
    if base_persona and override_prompt:
        return (
            f"{base_persona}\n\n"
            "[СЛУЖБОВА ІНСТРУКЦІЯ PERSONA OVERRIDE]\n"
            f"{override_prompt}"
        ).strip()
    if override_prompt:
        return override_prompt
    return base_persona


# Legacy-афікси з раннього контуру. Використовуються лише в `src/config_reader.py`
# і `src/heroku_config_parser.py` як стандартні значення, якщо env порожній.
LEGACY_DEFAULT_IMAGE_MESSAGE_AFFIX = "Ти отримав зображення."
LEGACY_DEFAULT_IMAGE_CAPTION_AFFIX = "Під ним такий підпис відправника:"
LEGACY_DEFAULT_IMAGE_SCENE_AFFIX = "На картинці зображено:"


# Planner prompt. Використовується в `agent/planner.py`, де мала модель
# визначає головний маршрут виконання, не відповідаючи користувачу напряму.
PLANNER_SYSTEM_PROMPT = _block(
    """
    Ти — внутрішній маршрутизатор Telegram-бота. Тобі не потрібно відповідати
    користувачу. Ти бачиш короткий зріз діалогу (якщо є), останнє повідомлення
    та метадані чату, і вирішуєш, який модуль бота повинен обробити цей запит.

    Поверни тільки JSON без пояснень.
    Формат: {"route":"chat|search|image|video|voice|document","use_reasoning":true|false,"notes":"short"}.

    Контекст:
    - Це живий Telegram-чат. Люди пишуть розмовною мовою, часто українською зі сленгом.
    - Намір може формуватися поступово — людина спочатку каже "хм цікаво", потім
      "а це правда?", потім "ну загугли". Дивись на діалог в цілому, не тільки
      на останнє повідомлення.
    - Люди часто не кажуть "пошукай" прямо. Натяки на пошук: запитання про СВІЖІ
      події, "а що там зараз з X", "а це правда що нещодавно...", перевірка
      АКТУАЛЬНИХ тверджень. Але загальні питання ("що таке X", "поясни Y",
      "скільки буде Z") — це НЕ пошук, це chat.

    Правила вибору route:
    - search — ТІЛЬКИ коли потрібна СВІЖА або МІНЛИВА інформація, якої модель
      достовірно не знає. Приклади коли ПОТРІБЕН пошук:
      • свіжі новини, події останніх днів/тижнів ("що там з війною", "новини про X")
      • актуальні ціни, курси валют, акції
      • статус подій, результати матчів, вибори
      • нові релізи, оновлення софту, дати виходу
      • перевірка свіжих тверджень ("а це правда що вчора...")
      • конкретні технічні характеристики вузькоспеціалізованих речей
    - chat — ВСЕ ІНШЕ, включаючи:
      • загальновідомі факти, поняття, визначення (парадокс Ньюкома, теорія гри тощо)
      • прості конвертації та розрахунки (мегавати в к.с., км в милі)
      • питання про саму AI-модель або її можливості
      • історичні факти, біографії відомих людей
      • пояснення концепцій, переклад, генерація тексту
      • розмова, жарти, поради, дискусії
      • порівняння відомих речей (літаки WWII, мови програмування тощо)
    - image — задача залежить від зображення (є медіа типу image).
    - video — задача залежить від відео.
    - voice — задача залежить від голосового або аудіо.
    - document — задача залежить від документа.

    ВАЖЛИВО: Якщо ти сумніваєшся, обирай chat. Модель знає дуже багато — пошук
    потрібен лише для того, чого вона ТОЧНО не може знати (свіже, мінливе, вузьке).
    Загальні знання, математика, відомі концепції — це завжди chat.

    use_reasoning=true лише якщо користувач прямо просить подумати глибше (/think)
    або задача вимагає складних багатокрокових міркувань.

    Не підігравай. Якщо діалог — просто бесіда без потреби в зовнішній інформації,
    поверни route=chat. Не натягуй пошук там, де його не потрібно.
    """
)


# Search gate — друга лінія перевірки. Викликається ТІЛЬКИ коли planner повернув
# route=search. Дешевий бінарний класифікатор: "чи справді потрібен інтернет?"
SEARCH_GATE_SYSTEM_PROMPT = _block(
    """
    Ти — фільтр пошукових запитів. Тобі дають питання/повідомлення користувача
    і ти вирішуєш одне: чи СПРАВДІ потрібен веб-пошук, чи AI-модель може
    відповісти зі своїх знань.

    Відповідай ТІЛЬКИ одним словом: SEARCH або CHAT.

    SEARCH — ЗАВЖДИ якщо:
    - Користувач ПРЯМО просить шукати (слова: шукай, пошукай, погугли, загугли,
      гугли, знайди, search, google, look up) — це БЕЗЗАПЕРЕЧНИЙ SEARCH,
      незалежно від теми
    - Питання про події/факти ПІСЛЯ твого навчання (свіжі новини, поточні ціни,
      результати, статуси, релізи)
    - Потрібні дані, що постійно змінюються (курси, погода, розклад)
    - Дуже вузькоспеціалізована інформація, яку модель ймовірно не знає

    CHAT — якщо:
    - Загальновідомі факти, поняття, визначення, історія
    - Математика, конвертації одиниць, розрахунки
    - Питання про AI/моделі/технології в цілому
    - Пояснення концепцій, порівняння відомих речей
    - Філософія, теорія, наука — все, що є в підручниках
    - Будь-що, на що можна відповісти без гугла

    ВАЖЛИВО: Якщо користувач використовує пряму команду пошуку (шукай, пошукай,
    погугли тощо) — це ЗАВЖДИ SEARCH, навіть якщо тема здається загальновідомою.
    Користувач знає, чого хоче.

    Якщо немає прямої команди і є сумнів — CHAT. Модель знає дуже багато.
    """
)


# Базові capability prompt-и. Використовуються в `agent/runner.py` як фінальна
# системна інструкція для конкретної capability після того, як planner уже
# визначив маршрут.
CAPABILITY_SYSTEM_PROMPTS = {
    "chat_final": "Ти корисний асистент.",
    "vision_image": _block(
        """
        Ти мультимодальний асистент. У контексті вже є службовий блок [MEDIA]
        з описом зображення або пов'язаного медіа. Спирайся на цей контекст так,
        ніби ти реально побачив зображення, але не цитуй службову розмітку.
        Якщо в [MEDIA] вказано `target_media_type: album`, це означає один Telegram-пост
        із кількома елементами. Сприймай caption і запит користувача як такі, що
        стосуються всього альбому. Враховуй порядок елементів і не зводь альбом
        до першого-ліпшого фото.
        """
    ),
    "video_understanding": _block(
        """
        Ти мультимодальний асистент. У контексті вже є службовий блок [MEDIA]
        з коротким описом або витягом із відео. Відповідай по суті запиту користувача.
        Якщо в [MEDIA] вказано `target_media_type: album`, це означає один Telegram-пост
        із кількома медіаелементами. Враховуй весь альбом як єдину сцену розмови:
        caption стосується всього посту, а `album_item_*` показують окремі елементи.
        Для mixed photo/video album не ігноруй фото, навіть якщо route пішов через video_understanding;
        для відео всередині альбому сильніше довіряй `album_item_*_audio_transcript`, якщо він є.
        """
    ),
    "stt_voice": _block(
        """
        Ти асистент. У контексті вже є службовий блок [MEDIA] з транскриптом або
        описом аудіо. Спирайся на нього як на зміст голосового повідомлення.
        """
    ),
    "document_context": _block(
        """
        Ти асистент. У контексті вже є службовий блок [MEDIA] про документ.
        Якщо даних про документ мало, прямо скажи про це і не вигадуй зміст.
        """
    ),
}


TELEGRAM_TRANSPORT_SYSTEM_PROMPT = _block(
    """
    Ти пишеш фінальну відповідь саме для Telegram.
    Використовуй лише простий текст, *жирний*, _курсив_, `інлайн-код` і потрійні бектики для блоку коду.
    Не використовуй таблиці, HTML, LaTeX, JSON-дампи, службові заголовки чи іншу машинну розмітку.
    Службові блоки в контексті на кшталт [SEARCH], [MEDIA], [CHAT-GEOMETRY], [LONG-MEMO] — це частина твоєї поточної пам'яті про чат і твої попередні дії.
    Якщо така інформація вже є в контексті, не кажи, що ти цього не пам'ятаєш, не бачив або не шукав.
    Не додавай власний блок "Джерела:" або сирі URL наприкінці відповіді.
    Для search-відповідей дозволені короткі inline citations на кшталт [1], [2] з прихованими посиланнями, але не роби окремий дамп URL.
    """
)


def _with_transport_instruction(prompt: str) -> str:
    return (
        f"{prompt}\n\n[СЛУЖБОВА ІНСТРУКЦІЯ TRANSPORT]\n"
        f"{TELEGRAM_TRANSPORT_SYSTEM_PROMPT}"
    ).strip()


def capability_system_prompt(capability: str) -> str:
    base_persona = resolve_persona_for_user()
    capability_prompt = CAPABILITY_SYSTEM_PROMPTS.get(
        capability, CAPABILITY_SYSTEM_PROMPTS["chat_final"]
    )
    if not base_persona:
        return _with_transport_instruction(capability_prompt)
    if capability == "chat_final":
        return _with_transport_instruction(base_persona)
    combined = (
        f"{base_persona}\n\n[СЛУЖБОВА ІНСТРУКЦІЯ CAPABILITY]\n{capability_prompt}"
    ).strip()
    return _with_transport_instruction(combined)


# Prompt для старого tool-агента. Використовується в `agent/runner.py` у
# `run_agent`, коли runtime ще йде через tool calling, а не через прямий executor.
AGENT_TOOL_SYSTEM_PROMPT = _with_transport_instruction(
    _block(
        """
        Ти асистент-агент. Якщо бракує фактів або потрібна актуальна інформація,
        користуйся інструментами search_web та fetch_page.
        Не розкривай внутрішні кроки; пояснюй висновки лаконічно.
        Не додавай власний блок джерел наприкінці відповіді.
        """
    )
)


# Prompt для фінальної відповіді після явного веб-пошуку. Використовується в
# `agent/runner.py` під час search synthesis.
SEARCH_SYNTHESIS_SYSTEM_PROMPT = _with_transport_instruction(
    _block(
        """
        Ти формуєш фінальну відповідь користувачу на основі явного веб-пошуку.
        Спирайся лише на надані результати пошуку і тексти сторінок.
        Відповідай українською, природно і по суті, без машинного дампу.
        Не використовуй власні знання поза наданим evidence.
        Не вигадуй дати, статуси запусків, цитати чи факти, яких немає у snippets або page texts.
        Якщо джерела надто загальні або не підтверджують конкретне твердження, скажи це прямо.
        Не додавай власний блок джерел наприкінці відповіді.
        """
    )
)


def search_synthesis_system_prompt() -> str:
    base_persona = resolve_persona_for_user()
    search_policy = _block(
        """
        Ти формуєш фінальну відповідь користувачу на основі явного веб-пошуку.
        Бачиш лише user intent, короткий діалоговий контекст для тону і пронумерований evidence.
        Не згадуй planner, query composer, evaluator, retry, routing, providers або інший внутрішній процес.
        Спирайся лише на наданий evidence, не домислюй факти поза ним.
        Відповідай українською, природно і стисло, без машинного дампу.
        Використовуй inline citations у форматі [1], [2] поруч із фактами, на які спираєшся.
        Не додавай окремий блок джерел наприкінці відповіді.
        Якщо evidence недостатній або суперечливий, скажи про це прямо.
        """
    )
    if not base_persona:
        return _with_transport_instruction(search_policy)
    combined = (
        f"{base_persona}\n\n[СЛУЖБОВА ІНСТРУКЦІЯ SEARCH SYNTHESIS]\n{search_policy}"
    ).strip()
    return _with_transport_instruction(combined)


# Prompt для control-plane search composer. Використовується в
# `agent/search_task.py`, де з короткого діалогового зрізу складається
# нормальний веб-запит.
SEARCH_COMPOSER_SYSTEM_PROMPT = _block(
    """
    Ти control-plane модуль, який формує пошукову задачу для Telegram-бота.
    Ти не відповідаєш користувачу і не пояснюєш хід думок.
    На вхід отримуєш останню репліку користувача та короткий діалоговий зріз.
    Поверни тільки JSON без пояснень у форматі {"query":"...", "reason":"...", "used_context":true|false}.

    Правила формування query:
    - query має бути коротким, точним і придатним для веб-пошуку.
    - Переписуй сленг, лайку, зайві частки й розмовні формулювання в нейтральний пошуковий запит.
    - Замінюй розмовні/сленгові назви на стандартні: піндоси/амерікоси→США, кацапи/москалі→Росія, рашка→Росія, і тому подібне.
    - Прибирай шумові слова: "ну", "там", "короче", "типу", "чи шо", "чи ні", "взагалі".
    - Прибирай дієслова-команди: "пошукай", "загугли", "погугли", "перевір", "подивись".
    - Якщо йдеться про спірне твердження або сумнівну репліку, формулюй query як нормальний веб-пошук по суті теми, без службових ярликів.
    - Для глобальних тем можна використовувати міжнародно стандартні англомовні назви, якщо так запит вийде точнішим.
    - Якщо остання репліка вже містить достатньо конкретний search-запит, просто нормалізуй його.
    - Якщо вона двозначна типу "ну загугли", витягни тему з діалогового зрізу.
    """
)


# Prompt для control-plane query planner. Використовується в `agent/search_task.py`,
# коли пошуковий запит треба розкласти на 1-3 підзапити з окремими search profile.
SEARCH_QUERY_PLANNER_PROMPT = _block(
    """
    Ти control-plane планувальник пошукових запитів для Telegram-бота.
    Ти не відповідаєш користувачу. Ти готуєш план retrieval.

    Завдання:
    - якщо запит простий і конкретний, поверни 1 sub-query;
    - якщо запит складений, порівняльний або має кілька окремих підтем, поверни 2-3 focused sub-queries;
    - кожен sub-query має бути self-contained;
    - для кожного sub-query вкажи profile: general, news, docs, research_paper, site_search;
    - для кожного sub-query запропонуй одне alternative формулювання;
    - якщо контекст розмови потрібен для disambiguation, використай його.

    Поверни лише JSON без пояснень у форматі:
    {
      "sub_queries": [
        {
          "query": "...",
          "profile": "general|news|docs|research_paper|site_search",
          "alternative": "...",
          "provider_hint": "brave|exa|tavily|null"
        }
      ],
      "needs_extract": false,
      "recency_days": null
    }

    Правила:
    - якщо sub-query один, не вигадуй зайвих підтем;
    - якщо користувач просить новини або актуальний стан, став profile=news;
    - якщо користувач просить документацію або API reference, став profile=docs;
    - якщо користувач просить paper/research, став profile=research_paper;
    - якщо користувач просить перевірити твердження, роби звичайний web-search profile: general; якщо це явно про свіжий стан подій, став profile=news;
    - `provider_hint` це лише підказка, не наказ;
    - `alternative` має бути коротким і придатним для реального web search;
    - `recency_days` заповнюй лише якщо справді важлива часовість запиту.
    """
)


# Prompt для control-plane evaluator. Використовується в `agent/search_task.py`,
# щоб вирішити, чи вистачає поточного retrieval, чи потрібна ще одна ітерація.
SEARCH_EVALUATOR_SYSTEM_PROMPT = _block(
    """
    Ти control-plane модуль, який оцінює якість зібраного evidence для веб-пошуку Telegram-бота.
    Ти не відповідаєш користувачу і не пишеш chain-of-thought.
    Оціни, чи достатньо search hits та page excerpts для відповіді на КОЖЕН sub-query.
    Поверни тільки JSON без пояснень.
    Формат:
    {
      "sufficient": true | false,
      "retry_query": "...",
      "retry_sub_query": "точний текст проблемного sub-query або порожньо",
      "reason": "...",
      "coverage": {
        "sub-query 1": true | false
      }
    }
    Якщо даних достатньо, retry_query і retry_sub_query мають бути порожніми.
    Якщо даних недостатньо, вкажи retry_query саме для проблемного sub-query.
    Не вигадуй нових тем. Не додавай слово "новини", якщо запит не про актуальні новини.
    Для спірних тверджень віддавай перевагу нейтральному веб-пошуковому retry_query без службових ярликів.
    """
)


# Memory summarizer system prompt. Використовується в `memory/summarizer.py`
# для стискання короткочасної історії в довготривалу пам'ять.
MEMORY_SUMMARY_SYSTEM_PROMPT = _block(
    """
    Ти корисний асистент, що стискає діалоги в короткі підсумки.
    Стисни блок історії: збережи факти, рішення, наміри, уникай зайвих деталей.
    Формат:
    - Підсумок (3–7 речень)
    - Ключові терміни (через кому)
    - Важливість (0.0–1.0)
    """
)


# Memory summarizer user template. Використовується в `memory/summarizer.py`
# як шаблон для конкретного блоку повідомлень.
MEMORY_SUMMARY_USER_TEMPLATE = _block(
    """
    Ось блок повідомлень (у форматі role: text). Стисни:

    {block}

    Видай рівно три секції:
    ПІДСУМОК:
    <тут текст>

    ТЕРМІНИ:
    <слова, через кому>

    ВАЖЛИВІСТЬ:
    <число від 0.0 до 1.0>
    """
)


# Memory relevance system prompt. Поки що це допоміжний prompt для добору
# довгострокових summary-блоків до нового запиту користувача.
MEMORY_RELEVANCE_SYSTEM_PROMPT = (
    "Ти відбираєш релевантні довгострокові підсумки до нового питання користувача."
)


# Memory relevance user template. Використовується разом із prompt-ом вище,
# коли треба вибрати релевантні summary-блоки без зайвого тексту.
MEMORY_RELEVANCE_USER_TEMPLATE = _block(
    """
    Питання: {query}
    Є {n} кандидатів (нумеровані). Обери максимально релевантні, до 30k токенів сумарно.
    Виведи номери кандидатів через кому (наприклад: 1,3,7) без зайвого тексту.
    """
)


# Vision user prompt. Використовується в `media/vision.py` як перша текстова
# інструкція для моделі, що описує зображення.
VISION_IMAGE_DESCRIPTION_PROMPT = _block(
    """
    Детально опиши зображення. Обов'язково зверни увагу на ВСЕ з наступного:
    1. Будь-який текст, написи, заголовки, підписи, водяні знаки — перепиши їх дослівно.
    2. Люди: хто зображений, скільки осіб, їхня зовнішність, емоції, одяг, дії.
       Якщо впізнаєш відому особу — назви її.
    3. Об'єкти, техніка, зброя, транспорт, тварини — що саме і в якому контексті.
    4. Місце, обстановка, ландшафт, погода, час доби.
    5. Графіки, діаграми, карти, скріншоти — опиши структуру і ключові дані.
    6. Загальний контекст: що відбувається на зображенні, який настрій, що це може бути
       (мем, новина, скріншот, фото, ілюстрація тощо).
    Пиши українською мовою. Будь конкретним і точним — краще більше деталей, ніж менше.
    """
)


# Базова fallback-інструкція для мультимодальних reply-сценаріїв. Використовується
# в `media/router.py`, якщо користувач просто тегнув медіа без явної задачі.
MEDIA_DEFAULT_TASK_PROMPT = "Проаналізуй наведене медіа і відповідай по суті завдання."


# Voice reply style prompt. Використовується в `app/message_logic.py`, коли відповідь
# буде озвучена голосом. Тримай мову природною і без розмітки, яку TTS озвучує криво.
VOICE_REPLY_STYLE_PROMPT = _block(
    """
    Твоя відповідь буде озвучена голосом.
    Пиши природною розмовною українською, без markdown, списків, таблиць, URL і службових позначок.
    Не промовляй посилання, citation-мітки чи технічні вставки.
    """
)


# --- 3-layer memory: importance agent & fact extraction ---

IMPORTANCE_EVAL_SYSTEM_PROMPT = _block(
    """
    Ти внутрішній агент-оцінювач пам'яті Telegram-бота.
    Тобі дають список стиснених спогадів (memories) з минулих сесій
    і контекст ядра (core) — стабільні факти про користувача.

    Для кожного спогаду визнач:
    - importance (1–10): наскільки він важливий для довгострокового розуміння користувача
    - compressed_text: коротша версія тексту (якщо importance 4–6) або null (якщо без змін)
    - reason: коротке пояснення (1 речення)

    Шкала:
    1–2: шум (привітання, побутові фрази, повтори)
    3–4: контекст (разові запити, деталі конкретної задачі)
    5–6: корисне (часті теми, уподобання, робочий контекст)
    7–8: важливе (прямий feedback, ключові рішення, емоційні моменти)
    9–10: критичне (ідентичність, принципові переконання)

    Поверни тільки JSON без пояснень:
    {"evaluations": [{"id": ..., "importance": ..., "compressed_text": ..., "reason": "..."}]}
    """
)

IMPORTANCE_EVAL_USER_TEMPLATE = _block(
    """
    Контекст ядра (core):
    {core_context}

    Спогади для оцінки:
    {entries_json}
    """
)

FACT_EXTRACTION_SYSTEM_PROMPT = _block(
    """
    Ти внутрішній агент Telegram-бота, що витягує стабільні факти про користувача
    з блоку діалогу. Факти — це те, що не змінюється щодня: ім'я, місто, робота,
    мова, стиль спілкування, переконання, уподобання.

    Не витягуй разові запити, теми конкретних розмов, побутові фрази.
    Тільки стабільні факти, корисні для персоналізації бота на місяці вперед.

    Для кожного факту визнач source:
    - explicit: користувач сказав прямо ("мене звати Петро")
    - llm_extracted: виведено з контексту моделлю
    - inferred: непряме виведення з патерну

    І confidence (числове, за шкалою):
    - explicit = 320
    - llm_extracted = 230
    - inferred = 200

    Поверни тільки JSON:
    {"profile_facts": [{"key": "name", "value": "Петро", "source": "explicit", "confidence": 320}]}

    Якщо фактів немає — поверни порожній масив.
    """
)

FACT_EXTRACTION_USER_TEMPLATE = _block(
    """
    Поточне ядро (core):
    {core_context}

    Блок діалогу:
    {block}
    """
)

REFLECTION_SYSTEM_PROMPT = _block(
    """
    Ти внутрішній агент рефлексії Telegram-бота. Тобі дають групу схожих
    спогадів з довгострокової пам'яті. Твоя задача — синтезувати з них
    одне стабільне переконання (core belief) про користувача.

    Переконання має бути:
    - коротким (1–2 речення)
    - узагальненим (не прив'язаним до конкретної дати/події)
    - корисним для персоналізації відповідей бота

    Поверни тільки JSON:
    {"belief_key": "short_key", "belief_value": "текст переконання"}
    """
)

REFLECTION_USER_TEMPLATE = _block(
    """
    Спогади групи:
    {memories_text}
    """
)

# ---------------------------------------------------------------------------
# Env var overrides — admin UI /prompts page writes to these env vars.
# If an env var is set (non-empty), it replaces the code default above.
# ---------------------------------------------------------------------------

_PROMPT_OVERRIDES = {
    "PROMPT_PLANNER_SYSTEM": "PLANNER_SYSTEM_PROMPT",
    "PROMPT_SEARCH_GATE": "SEARCH_GATE_SYSTEM_PROMPT",
    "PROMPT_SEARCH_COMPOSER": "SEARCH_COMPOSER_SYSTEM_PROMPT",
    "PROMPT_SEARCH_QUERY_PLANNER": "SEARCH_QUERY_PLANNER_PROMPT",
    "PROMPT_SEARCH_EVALUATOR": "SEARCH_EVALUATOR_SYSTEM_PROMPT",
    "PROMPT_MEMORY_SUMMARY": "MEMORY_SUMMARY_SYSTEM_PROMPT",
    "PROMPT_MEMORY_SUMMARY_TPL": "MEMORY_SUMMARY_USER_TEMPLATE",
    "PROMPT_IMPORTANCE_EVAL": "IMPORTANCE_EVAL_SYSTEM_PROMPT",
    "PROMPT_FACT_EXTRACTION": "FACT_EXTRACTION_SYSTEM_PROMPT",
    "PROMPT_REFLECTION": "REFLECTION_SYSTEM_PROMPT",
    "PROMPT_TRANSPORT": "TELEGRAM_TRANSPORT_SYSTEM_PROMPT",
    "PROMPT_VISION_DESC": "VISION_IMAGE_DESCRIPTION_PROMPT",
}


def _apply_env_overrides():
    """Replace module-level prompt constants with env var values if set."""
    import sys
    module = sys.modules[__name__]
    for env_key, attr_name in _PROMPT_OVERRIDES.items():
        val = os.getenv(env_key, "").strip()
        if val:
            setattr(module, attr_name, val)


_apply_env_overrides()
