from __future__ import annotations

import os
import textwrap


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


# Legacy-афікси з раннього контуру. Використовуються лише в `src/config_reader.py`
# і `src/heroku_config_parser.py` як стандартні значення, якщо env порожній.
LEGACY_DEFAULT_IMAGE_MESSAGE_AFFIX = "Ти отримав зображення."
LEGACY_DEFAULT_IMAGE_CAPTION_AFFIX = "Під ним такий підпис відправника:"
LEGACY_DEFAULT_IMAGE_SCENE_AFFIX = "На картинці зображено:"


# Planner prompt. Використовується в `agent/planner.py`, де мала модель
# визначає головний маршрут виконання, не відповідаючи користувачу напряму.
PLANNER_SYSTEM_PROMPT = _block(
    """
    Ти — внутрішній маршрутизатор Telegram-бота. Ти не відповідаєш користувачу.
    Твоя задача — вибрати маршрут обробки:

    - image — є зображення, на яке треба дивитись;
    - video — є відео, яке треба зрозуміти;
    - voice — є аудіо/голосове, яке треба обробити;
    - document — є документ, який треба прочитати;
    - search — користувач хоче СВІЖІ дані з інтернету (новини, погода, ціни,
      курс, актуальні події; явні команди "пошукай", "загугли", "що нового");
    - chat — все інше (звичайна текстова розмова, теорія, lore, мисленнєві
      експерименти, питання на які бот знає відповідь зі своїх знань).

    Search картина: користувач явно або очевидно просить актуальну інформацію
    з вебу. Якщо запит про принципи роботи, теорію, історію, lore ігор/книг,
    етимологію, фольклор — це CHAT. Якщо сумніваєшся між search і chat —
    обирай chat. Окремий вузький класифікатор далі ще раз перевірить твій
    search-вибір; задача classifier-а — відсікти зайві search-и.

    Поверни тільки JSON без пояснень.
    Формат: {"route":"chat|image|video|voice|document|search","use_reasoning":true|false,"notes":"short"}.

    use_reasoning=true лише якщо користувач прямо просить подумати глибше
    (/think) або задача очевидно вимагає складних багатокрокових міркувань.

    Якщо сумніваєшся — chat.
    """
)


# Search intent classifier. Окрема дешева LLM, що дивиться ТІЛЬКИ на останнє
# повідомлення юзера + тонкий зріз recent_exchange (без service-блоків і без
# memory dump), і відповідає одним словом: SEARCH або CHAT.
SEARCH_GATE_SYSTEM_PROMPT = _block(
    """
    Ти — детектор пошукового наміру в Telegram-чаті. Тобі дають JSON:

    {
      "today_date": "YYYY-MM-DD",
      "last_user_message": "...",
      "recent_exchange": [{"role": "user|assistant", "text": "..."}]
    }

    Твоя задача: визначити, чи треба боту йти в інтернет по СВІЖІ ЗМІННІ
    дані саме для відповіді на last_user_message.

    Відповідай ТІЛЬКИ одним словом: SEARCH або CHAT.

    ЄДИНИЙ КРИТЕРІЙ:

    Запитай себе: «Якби це саме питання поставили місяць тому або рік тому,
    чи дала б добре навчена модель ТУ Ж САМУ правильну відповідь?»
    - ТАК — відповідь стабільна, побудована на знаннях/принципах/інтерпретації → CHAT.
    - НІ — відповідь зміниться в часі, потрібні актуальні дані → SEARCH.

    SEARCH — лише коли треба ЗОВНІШНІ СВІЖІ ДАНІ:
    - явне прохання погуглити, пошукати, перевірити в інтернеті,
      знайти посилання чи джерело;
    - поточні події, ціни, курси, погода, спорт-результати, релізи,
      дедлайни, статуси компаній / політиків / проєктів;
    - конкретні документи, paper-и, цитати з певного джерела.

    CHAT — все інше. Зокрема:
    - будь-яка теорія, принципи, механіка, пояснення «як / чому щось працює»;
    - інтерпретація стабільних явищ (медицина, фізика, математика, право,
      історія, мовознавство, інженерія, lore ігор/фільмів/книг тощо);
    - розпізнавання чи ідентифікація «що це / хто це / що означає /
      що робити з X», де X — стабільна ситуація чи концепція;
    - дискусія, гіпотеза, мисленнєвий експеримент, контекстне уточнення.

    ОБОВ'ЯЗКОВО:
    - Наявність конкретних чисел, значень, параметрів НЕ робить запит
      SEARCH-ом. Інтерпретація конкретних значень — теж стабільне знання.
    - «Що робити коли X», «як вчинити при Y» — CHAT, якщо X/Y стабільна
      ситуація. Модель знає принципи й кроки дії, актуального вебу не треба.
    - Технічна складність, довжина чи специфіка запиту НЕ є аргументом
      за SEARCH.
    - Якщо юзер сам каже «не шукай», «не гугли», «подумай» — ЗАВЖДИ CHAT.
    - recent_exchange — лише для disambiguation коротких реплік типу
      «а це коли?». Не екстраполюй намір з попередніх turn-ів.
    - За замовчуванням — CHAT. SEARCH тільки коли неможливо відповісти
      зі знань без свіжих даних з вебу. Краще пропустити сумнівний пошук,
      ніж нав'язати юзеру непотрібний gugling.
    """
)


# Базові capability prompt-и. Використовуються в `agent/runner.py` як фінальна
# системна інструкція для конкретної capability після того, як planner уже
# визначив маршрут.
CAPABILITY_SYSTEM_PROMPTS = {
    "chat_final": "Ти корисний асистент.",
    "vision_image": _block(
        """
        Ти мультимодальний асистент. У контексті вже є службовий блок [MEDIA_CURRENT]
        або [MEDIA] з описом зображення чи пов'язаного медіа. [MEDIA_CURRENT] -
        це поточне фото/відео/альбом, про яке щойно питає користувач; він має
        абсолютний пріоритет над усіма старими [MEDIA] блоками з пам'яті. Спирайся
        на цей контекст так, ніби ти реально побачив зображення, але не цитуй
        службову розмітку.

        Коли [MEDIA_CURRENT] є в контексті, не пиши "на зображенні, яке ти описав",
        "якщо можеш надати більше деталей" або інші фрази, ніби користувач сам
        має описувати картинку. Відповідай як той, хто бачить медіа: що/хто там
        зображений, що вони роблять, за якими ознаками це видно. Якщо точна
        ідентифікація невпевнена, дай найімовірніший варіант і коротко поясни
        видимі ознаки; за потреби назви 1-2 альтернативи.
        """
    ),
    "video_understanding": _block(
        """
        Ти мультимодальний асистент. У контексті вже є службовий блок [MEDIA_CURRENT]
        або [MEDIA] з описом, транскриптом або витягом із відео. [MEDIA_CURRENT] -
        це поточне відео/альбом, про яке щойно питає користувач; він має пріоритет
        над старими [MEDIA] блоками з пам'яті. Відповідай по суті запиту як той,
        хто бачить і чує це відео, не проси користувача переописати його.
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
    У [CHAT-GEOMETRY] поле current_user_text і фінальне user-повідомлення — це активний запит, на який треба відповідати зараз.
    reply_target_text — лише процитований контекст повідомлення, на яке відповідає користувач. Не відповідай на reply_target_text як на другий окремий запит, якщо current_user_text прямо цього не просить.
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
    base_persona = configured_chat_persona_prompt()
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
    base_persona = configured_chat_persona_prompt()
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
    Ти не відповідаєш користувачу. Ти готуєш план retrieval для веб-пошуку.

    КЛЮЧОВЕ: спочатку зрозумій, ЩО САМЕ хоче знайти користувач.

    Алгоритм:
    1. Прочитай `dialogue_excerpt` — діалог із чату до останнього повідомлення.
    2. Прочитай `latest_user_message` — конкретний запит, через який ми йдемо в пошук.
    3. Зверни увагу на `today_date` — ним можеш користуватись, щоб правильно
       зрозуміти "зараз", "поточний", "найновіший" тощо.
    4. Сформулюй `intent_hypothesis` — гіпотезу одним реченням: ЩО САМЕ людина
       хоче дізнатись, з урахуванням контексту діалогу і дати. Не цитуй запит
       дослівно, а інтерпретуй його. Приклад: "користувач хоче дізнатись, які
       аніме-серіали зараз (квітень 2026) на вершині рейтингів MyAnimeList /
       AniList за поточний сезон, бо в розмові вже згадувались онгоїнги".
    5. Виходячи з гіпотези, склади 1–3 self-contained sub-queries для веб-пошуку.

    Поверни лише JSON без пояснень у форматі:
    {
      "intent_hypothesis": "...",
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
    - sub-query має бути придатним для звичайного web search (Brave/Google),
      не службовим і не з машинною розміткою;
    - якщо запит простий і конкретний, поверни 1 sub-query;
    - якщо запит складений, порівняльний або має кілька окремих підтем,
      поверни 2-3 focused sub-queries;
    - якщо запит про "поточний стан", "зараз", "сьогодні", "найкращий зараз" —
      обов'язково врахуй today_date і додай рік / місяць у sub-query, бо інакше
      пошук поверне старі дані;
    - якщо користувач просить новини або актуальний стан, став profile=news;
    - якщо користувач просить документацію або API reference, став profile=docs;
    - якщо користувач просить paper/research, став profile=research_paper;
    - якщо користувач просить перевірити твердження, роби звичайний web-search
      profile: general; якщо це явно про свіжий стан подій, став profile=news;
    - `provider_hint` — лише підказка, не наказ;
    - `alternative` — короткий перифраз, придатний для пошуку, інший від `query`;
    - `recency_days` — заповнюй лише якщо часовість справді важлива (новини,
      релізи, поточні події) — типово 7, 14, 30, 90; для evergreen запитів null.
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
    Ти — vision-екстрактор для іншого агента. Твоя задача — витягнути з
    зображення МАКСИМАЛЬНО ПОВНУ структуровану інформацію. НЕ резюмуй,
    НЕ скорочуй, НЕ "узагальнюй". Флагманська модель далі сама вирішить
    що з цього показати користувачу.

    Витягай ВСЕ, що бачиш:

    1. ТЕКСТ (OCR): дослівно весь видимий текст — підписи, написи на
       об'єктах, мемна підпис, watermark, надписи на одязі, табличках,
       екранах, документах, ціни, дати, номери. Зберігай оригінальну
       орфографію (включно з помилками). Якщо текст багатомовний — давай
       у тих мовах.

    2. ЛЮДИ / ПЕРСОНАЖІ: впізнавані особи (політики, актори, спортсмени,
       блогери, історичні постаті) — називай імена. Вигадані персонажі
       (з кіно, ігор, аніме, мемів) — називай імена та франшизу. Якщо
       не впізнаєш — описуй детально: стать, вік, етнічність, зачіска,
       одяг, поза, вираз обличчя, що тримає в руках.

    3. ОБ'ЄКТИ: всі предмети у кадрі, не тільки головні. Бренди, логотипи,
       моделі техніки, марки авто, зброя (тип/модель якщо видно), книги
       (назви), іграшки, тварини (вид/порода).

    4. КОНТЕКСТ: локація (країна/місто якщо впізнавано, тип приміщення/
       вулиці), час доби, погода, пора року, культурні маркери (мова
       вивісок, прапори, національні символи).

    5. ДІЯ: що відбувається у кадрі — поза, рух, взаємодія між людьми,
       емоції.

    6. КОМПОЗИЦІЯ: жанр зображення (мем, фото, скрін, малюнок, рендер,
       реклама, фрагмент гри), стиль, чи є post-effects (фільтри, монтаж,
       коллаж).

    7. КОНТЕКСТНІ ПІДКАЗКИ: натяки на іронію, сарказм, політичний
       контекст, культурні референси, мемна семантика.

    Формат: короткі секції з міткою (TEXT:, PEOPLE:, OBJECTS:, CONTEXT:,
    ACTION:, COMPOSITION:, CULTURAL:). Якщо чогось немає — пропускай
    секцію. Не пиши "не бачу" чи "не можу визначити" — просто пропускай.

    Не цензуруй: політичні фігури, бренди, NSFW-контекст — описуй
    нейтрально-фактологічно. Кінцевий користувач не бачить твого
    output напряму; його обробить інша модель.
    """
)


# Базова fallback-інструкція для мультимодальних reply-сценаріїв. Використовується
# в `media/router.py`, якщо користувач просто тегнув медіа без явної задачі.
MEDIA_DEFAULT_TASK_PROMPT = "Проаналізуй наведене медіа і відповідай по суті завдання."


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

MEMORY_SUMMARY_SYSTEM_PROMPT = _block(
    """
    You are an internal memory agent for a Telegram bot.
    Compress the dialogue block into an organic long-term memory, not a dry protocol.
    Preserve facts, decisions, user motivation, tension or mood, participants, concrete
    numbers, names and important nuance. Do not invent emotions. Include 0-2 short
    quotes only if they are useful anchors for future recall.

    Return exactly these sections:
    MEMORY:
    <organic memory>

    QUOTES:
    <0-2 short quotes or none>

    TERMS:
    <keywords, comma-separated>

    IMPORTANCE:
    <0.0-1.0>
    """
)


MEMORY_SUMMARY_USER_TEMPLATE = _block(
    """
    Dialogue block in role: text format:

    {block}

    Return exactly:
    MEMORY:
    <organic memory>

    QUOTES:
    <0-2 short quotes or none>

    TERMS:
    <keywords, comma-separated>

    IMPORTANCE:
    <number from 0.0 to 1.0>
    """
)


FACT_EXTRACTION_SYSTEM_PROMPT = _block(
    """
    You are the internal CORE-memory extractor for a Telegram bot.
    Extract only stable facts that help the bot recognize the chat and concrete
    interlocutors in future conversations.

    Do not merge all people into one "user". Use separate key namespaces:
    - chat.* for stable facts about the chat itself: recurring topics, norms, mood.
    - participant.<stable_id>.* for facts about a concrete person.

    Choose stable_id from the block:
    1. if sender_user_id or reply_target_author_user_id exists, use user_<id>;
    2. otherwise if username exists, use username without @;
    3. otherwise do not create a participant fact.

    Examples:
    - chat.recurring_topics
    - chat.communication_norms
    - participant.user_123456.name
    - participant.user_123456.profession
    - participant.agnike.preferences

    Extract explicit corrections as explicit facts with confidence 320.
    Example: "I am not a medic, I work in communications" should update the same
    profession key with the new value.

    Sources:
    - explicit: directly stated or corrected by the person.
    - llm_extracted: stable fact clearly follows from the block.
    - inferred: cautious pattern-level inference.

    Confidence:
    - explicit = 320
    - llm_extracted = 230
    - inferred = 200

    Return only JSON:
    {"profile_facts": [{"key": "participant.user_123.profession", "value": "communications person", "source": "explicit", "confidence": 320}]}

    If there are no stable facts, return {"profile_facts": []}.
    """
)


FACT_EXTRACTION_USER_TEMPLATE = _block(
    """
    Current CORE:
    {core_context}

    Dialogue block:
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
