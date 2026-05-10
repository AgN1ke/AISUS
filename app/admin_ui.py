from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlparse

from memory import memory_manager

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER_ENV_PATH = Path("/opt/smartest/.env")
ENV_PATH = Path(
    os.getenv("SMARTEST_ENV_PATH")
    or (
        DEFAULT_SERVER_ENV_PATH
        if DEFAULT_SERVER_ENV_PATH.exists()
        else PROJECT_ROOT / ".env"
    )
)
COOKIE_NAME = "smartest_admin_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
HOST = os.getenv("SMARTEST_ADMIN_HOST", "127.0.0.1")
PORT = int(os.getenv("SMARTEST_ADMIN_PORT", "8787"))
MANAGED_BOT_SERVICE = os.getenv("SMARTEST_MANAGED_SERVICE", "smartest-bot.service")
SELF_SERVICE_NAME = os.getenv("SMARTEST_ADMIN_SERVICE_NAME", "smartest-admin.service")

# ---------------------------------------------------------------------------
# Provider definitions — base URLs are code constants, not user-facing
# ---------------------------------------------------------------------------

BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "anthropic": "",
    "mistral": "",
    "xai": "",
}

@dataclass(frozen=True)
class ProviderDef:
    slug: str
    label: str
    kind: str  # "llm" or "search"
    key_env: str
    help_text: str = ""

PROVIDERS: list[ProviderDef] = [
    ProviderDef("openai", "OpenAI", "llm", "PROVIDER_OPENAI_API_KEY",
                "GPT-4o, o-серія, whisper, tts"),
    ProviderDef("anthropic", "Anthropic", "llm", "PROVIDER_ANTHROPIC_API_KEY",
                "Claude моделі"),
    ProviderDef("gemini", "Google Gemini", "llm", "PROVIDER_GEMINI_API_KEY",
                "Vision, video, grounded search"),
    ProviderDef("deepseek", "DeepSeek", "llm", "PROVIDER_DEEPSEEK_API_KEY",
                "Дешевий reasoning"),
    ProviderDef("mistral", "Mistral", "llm", "PROVIDER_MISTRAL_API_KEY",
                "Mistral Large/Small"),
    ProviderDef("xai", "xAI (Grok)", "llm", "PROVIDER_XAI_API_KEY",
                "Grok-3"),
    ProviderDef("brave", "Brave Search", "search", "PROVIDER_BRAVE_API_KEY",
                "Primary search"),
    ProviderDef("tavily", "Tavily", "search", "PROVIDER_TAVILY_API_KEY",
                "Search + extract"),
    ProviderDef("exa", "Exa", "search", "PROVIDER_EXA_API_KEY",
                "Docs, papers"),
    ProviderDef("serper", "Serper", "search", "PROVIDER_SERPER_API_KEY",
                "Google wrapper"),
    ProviderDef("perplexity", "Perplexity", "search", "PROVIDER_PERPLEXITY_API_KEY",
                "LLM search"),
    ProviderDef("bing", "Bing", "search", "PROVIDER_BING_API_KEY",
                "Fallback"),
]

# Detailed info for search provider tooltips
SEARCH_PROVIDER_INFO: dict[str, str] = {
    "brave": "Найкращий за якістю (score 14.89/20, #1 з 8 API). Швидкий: 669ms. Ціна: $5-9/1K запитів. Free tier: 2000 запитів/місяць. Рекомендований як primary.",
    "tavily": "Search + витяг контенту зі сторінок. Єдиний хто може crawl сайт і дати чистий текст. Ціна: $5/1K. Free tier: 1000 запитів/місяць. Добрий для site-search.",
    "exa": "Семантичний пошук — шукає за змістом, а не ключовими словами. Ідеальний для наукових статей, документації, technical research. Ціна: $3.50/1K. Free tier: 1000 запитів/місяць.",
    "serper": "Обгортка над Google Search. Стабільний, швидкий. Ціна: $1/1K. Free tier: 2500 запитів. Добрий fallback.",
    "perplexity": "LLM-powered пошук — не просто посилання, а готова синтезована відповідь. Повільний (~11с). Ціна: $5/1K. Free tier: немає. Корисний для складних питань.",
    "bing": "Microsoft Bing API. Старий, стабільний. Ціна: перші 1000 безплатно, далі $7/1K. Fallback якщо все інше не працює.",
}

LLM_PROVIDERS = [p for p in PROVIDERS if p.kind == "llm"]
SEARCH_PROVIDERS = [p for p in PROVIDERS if p.kind == "search"]

# ---------------------------------------------------------------------------
# Model catalogues per provider and model_type
# ---------------------------------------------------------------------------

MODELS: dict[str, dict[str, list[str]]] = {
    "text": {
        # GPT-5.4 = flagship April 2026; 5.4-mini = fast/cheap; 4.1 = older still available
        "openai": ["gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "o4-mini"],
        # Claude 4.6 = current gen (April 2026)
        "anthropic": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
        # Gemini 3.1-pro = latest (paid tier only); 2.5 = stable; 2.5-flash-lite = cheapest
        "gemini": ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
        # DeepSeek V3 = deepseek-chat; R1 = deepseek-reasoner
        "deepseek": ["deepseek-chat", "deepseek-reasoner"],
        # Mistral Large 3, Medium 3, Small 4 (March 2026)
        "mistral": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest", "codestral-latest"],
        # Grok 4 = new flagship; Grok 3 = stable
        "xai": ["grok-4", "grok-3", "grok-3-mini"],
    },
    "vision": {
        "openai": ["gpt-5.4", "gpt-5.4-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4o"],
        "anthropic": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
        "gemini": ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
    },
    "video": {
        # Only Gemini has native video input (April 2026)
        "gemini": ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
    },
    "stt": {
        # OpenAI transcribe models (April 2026)
        "openai": ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"],
    },
}

# ---------------------------------------------------------------------------
# Capability definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilityDef:
    slug: str
    title: str
    help_text: str
    group: str          # "smart", "functional", "media"
    recommendation: str  # human-readable model guidance
    model_type: str     # "text", "vision", "video", "stt"
    default_provider: str
    default_model: str

CAPABILITIES: list[CapabilityDef] = [
    # --- Smart: need strong models ---
    CapabilityDef(
        "chat_final", "Текстова відповідь",
        "Головна модель для звичайних відповідей у чаті.",
        "smart", "Потужна модель (GPT-5.4-mini, Claude Sonnet, Gemini 2.5 Pro)",
        "text", "openai", "gpt-5.4-mini",
    ),
    CapabilityDef(
        "search_synthesis", "Пошукова відповідь",
        "Формує фінальну відповідь з цитатами на основі знайдених джерел.",
        "smart", "Потужна модель",
        "text", "openai", "gpt-5.4-mini",
    ),
    CapabilityDef(
        "agent_reasoning", "Tool Agent",
        "Виклик інструментів і reasoning з tool-call ланцюжком.",
        "smart", "Потужна модель з tool use",
        "text", "openai", "gpt-5.4-mini",
    ),
    # --- Functional: cheap small models ---
    CapabilityDef(
        "planner_reasoning", "Planner / Router",
        "Визначає маршрут: чат, пошук, зображення, голос.",
        "functional", "Маленька дешева (GPT-5.4-nano, Haiku, Flash-Lite)",
        "text", "openai", "gpt-5.4-nano",
    ),
    CapabilityDef(
        "search_query_planner", "Декомпозиція запитів",
        "Розбиває складні запити на 1-3 підзапити.",
        "functional", "Маленька дешева",
        "text", "openai", "gpt-5.4-nano",
    ),
    CapabilityDef(
        "search_query_composer", "Побудова пошукових запитів",
        "Перетворює діалог у чистий пошуковий запит.",
        "functional", "Маленька дешева",
        "text", "openai", "gpt-5.4-nano",
    ),
    CapabilityDef(
        "search_evaluator", "Оцінка результатів",
        "Оцінює якість знайденого і вирішує чи потрібен retry.",
        "functional", "Маленька дешева",
        "text", "openai", "gpt-5.4-nano",
    ),
    CapabilityDef(
        "memory_summary", "Стиснення пам'яті",
        "Стискає історію розмови в довготривалі підсумки.",
        "functional", "Маленька дешева",
        "text", "openai", "gpt-5.4-nano",
    ),
    # --- Media: specific model capabilities required ---
    CapabilityDef(
        "vision_image", "Розпізнавання зображень",
        "Аналіз фото, мемів, скріншотів.",
        "media", "Тільки моделі з vision",
        "vision", "openai", "gpt-5.4-mini",
    ),
    CapabilityDef(
        "video_understanding", "Розуміння відео",
        "Аналіз відео з native video input.",
        "media", "Тільки Gemini (єдиний з native video)",
        "video", "gemini", "gemini-2.5-flash",
    ),
    CapabilityDef(
        "stt_voice", "Чат-відповідь на голос",
        "Чат-капабіліті, що формує відповідь на вже транскрибований текст. "
        "Сама транскрипція робиться окремим Whisper API викликом у секції Voice & STT.",
        "smart", "Текстова модель (та сама що chat_final або легша)",
        "text", "openai", "gpt-4o-mini",
    ),
    CapabilityDef(
        "document_context", "Робота з документами",
        "Аналіз документів і текстових вкладень.",
        "media", "Модель з великим контекстом",
        "text", "openai", "gpt-5.4-mini",
    ),
]

CAPABILITY_GROUPS = [
    ("smart", "Розумні Агенти", "Формують відповіді користувачу. Потребують потужних моделей."),
    ("functional", "Функціональні Агенти", "Внутрішні задачі: routing, пошукові запити, оцінка. Працюють на маленьких дешевих моделях."),
    ("media", "Медіа Агенти", "Працюють з конкретними форматами. Список моделей обмежений можливостями."),
]

# ---------------------------------------------------------------------------
# Prompt definitions — for the /prompts page
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptDef:
    slug: str           # unique id
    title: str          # human-readable name
    description: str    # what it does
    stage: str          # at which pipeline stage
    capability: str     # which capability uses this (for model resolution)
    env_key: str        # env var to override this prompt
    code_default: str   # default value from core/prompts.py

def _load_prompt_defaults() -> dict[str, str]:
    """Load default prompt values from core/prompts.py at import time."""
    from core.prompts import (
        PLANNER_SYSTEM_PROMPT,
        SEARCH_GATE_SYSTEM_PROMPT,
        SEARCH_COMPOSER_SYSTEM_PROMPT,
        SEARCH_QUERY_PLANNER_PROMPT,
        SEARCH_EVALUATOR_SYSTEM_PROMPT,
        MEMORY_SUMMARY_SYSTEM_PROMPT,
        MEMORY_SUMMARY_USER_TEMPLATE,
        TELEGRAM_TRANSPORT_SYSTEM_PROMPT,
        VISION_IMAGE_DESCRIPTION_PROMPT,
        IMPORTANCE_EVAL_SYSTEM_PROMPT,
        FACT_EXTRACTION_SYSTEM_PROMPT,
        REFLECTION_SYSTEM_PROMPT,
    )
    return {
        "planner": PLANNER_SYSTEM_PROMPT,
        "search_gate": SEARCH_GATE_SYSTEM_PROMPT,
        "search_composer": SEARCH_COMPOSER_SYSTEM_PROMPT,
        "search_query_planner": SEARCH_QUERY_PLANNER_PROMPT,
        "search_evaluator": SEARCH_EVALUATOR_SYSTEM_PROMPT,
        "memory_summary": MEMORY_SUMMARY_SYSTEM_PROMPT,
        "memory_summary_tpl": MEMORY_SUMMARY_USER_TEMPLATE,
        "transport": TELEGRAM_TRANSPORT_SYSTEM_PROMPT,
        "vision_desc": VISION_IMAGE_DESCRIPTION_PROMPT,
        "importance_eval": IMPORTANCE_EVAL_SYSTEM_PROMPT,
        "fact_extraction": FACT_EXTRACTION_SYSTEM_PROMPT,
        "reflection": REFLECTION_SYSTEM_PROMPT,
    }

_PROMPT_DEFAULTS: dict[str, str] = {}

def _get_prompt_defaults() -> dict[str, str]:
    global _PROMPT_DEFAULTS
    if not _PROMPT_DEFAULTS:
        _PROMPT_DEFAULTS = _load_prompt_defaults()
    return _PROMPT_DEFAULTS

PROMPT_DEFS: list[PromptDef] = [
    PromptDef(
        "persona", "Персона бота",
        "Головний system prompt, що визначає характер і стиль бота. Додається до кожної відповіді.",
        "Кожна відповідь",
        "chat_final",
        "SYSTEM_MESSAGES_GPT_PROMPT",
        "",
    ),
    PromptDef(
        "planner", "Planner / Router",
        "Внутрішній маршрутизатор. Визначає, який модуль обробить запит: чат, пошук, зображення, голос, документ.",
        "Крок 1: Маршрутизація",
        "planner_reasoning",
        "PROMPT_PLANNER_SYSTEM",
        "",
    ),
    PromptDef(
        "search_gate", "Search Gate (відсікач пошуку)",
        "Класифікатор-фільтр. Запускається тільки коли planner вибрав search; "
        "відсікає false positives: lore, теорію, мисленнєві експерименти. Fail-closed: помилка -> CHAT.",
        "Крок 1.5: Verify search decision",
        "planner_reasoning",
        "PROMPT_SEARCH_GATE",
        "",
    ),
    PromptDef(
        "search_composer", "Побудова пошукового запиту",
        "Перетворює розмовний запит користувача в чистий пошуковий запит. Прибирає сленг, зайві слова, команди.",
        "Крок 2a: Пошук → формулювання",
        "search_query_composer",
        "PROMPT_SEARCH_COMPOSER",
        "",
    ),
    PromptDef(
        "search_query_planner", "Декомпозиція запитів",
        "Розбиває складний запит на 1–3 підзапити з профілем (general/news/docs) та альтернативним формулюванням.",
        "Крок 2b: Пошук → планування",
        "search_query_planner",
        "PROMPT_SEARCH_QUERY_PLANNER",
        "",
    ),
    PromptDef(
        "search_evaluator", "Оцінка результатів пошуку",
        "Оцінює, чи вистачає знайденого evidence для відповіді, і чи потрібен retry з іншим запитом.",
        "Крок 2c: Пошук → оцінка",
        "search_evaluator",
        "PROMPT_SEARCH_EVALUATOR",
        "",
    ),
    PromptDef(
        "memory_summary", "Стиснення пам'яті (system)",
        "Стискає блок діалогу з Working-шару в короткий підсумок для Long-term пам'яті.",
        "Консолідація: Working → Long-term",
        "memory_summary",
        "PROMPT_MEMORY_SUMMARY",
        "",
    ),
    PromptDef(
        "memory_summary_tpl", "Стиснення пам'яті (шаблон)",
        "Шаблон для конкретного блоку повідомлень. Змінна {block} замінюється на текст.",
        "Консолідація: Working → Long-term",
        "memory_summary",
        "PROMPT_MEMORY_SUMMARY_TPL",
        "",
    ),
    PromptDef(
        "importance_eval", "Оцінка важливості спогадів",
        "Агент-оцінювач: визначає важливість (1–10) кожного спогаду при каскадному перестисненні Long-term.",
        "Каскадне перестиснення Long-term",
        "memory_summary",
        "PROMPT_IMPORTANCE_EVAL",
        "",
    ),
    PromptDef(
        "fact_extraction", "Витяг фактів → CORE",
        "Витягує стабільні факти про користувача (ім'я, місто, робота, стиль) з блоку діалогу в CORE-шар пам'яті.",
        "Консолідація → CORE шар",
        "memory_summary",
        "PROMPT_FACT_EXTRACTION",
        "",
    ),
    PromptDef(
        "reflection", "Рефлексія (синтез beliefs)",
        "Аналізує групу схожих спогадів і формує одне стабільне переконання (core belief) про користувача.",
        "Рефлексія (раз на 3 дні)",
        "memory_summary",
        "PROMPT_REFLECTION",
        "",
    ),
    PromptDef(
        "transport", "Telegram формат",
        "Інструкція з форматування відповідей для Telegram. Додається до кожної фінальної відповіді.",
        "Кожна відповідь (transport layer)",
        "chat_final",
        "PROMPT_TRANSPORT",
        "",
    ),
    PromptDef(
        "vision_desc", "Опис зображень",
        "Коротка інструкція для моделі, що описує зображення: текст на картинці, персонажі, дії.",
        "Медіа: розпізнавання зображень",
        "vision_image",
        "PROMPT_VISION_DESC",
        "",
    ),
]

# Adapter auto-detection — internal, never shown to user
def _auto_adapter(provider: str, model_type: str) -> str:
    if provider == "gemini":
        return "gemini_generate_content"
    if model_type == "vision":
        return "openai_vision"
    return "openai_chat"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnvLine:
    kind: str
    raw: str
    key: str = ""
    value: str = ""

@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    placeholder: str = ""
    input_type: str = "text"
    help_text: str = ""

# Build flat PROVIDER_FIELDS for backward compat in tests
PROVIDER_FIELDS: list[FieldDef] = [
    FieldDef(p.key_env, f"{p.label} API key", input_type="password", help_text=p.help_text)
    for p in PROVIDERS
]

GLOBAL_FIELDS: list[FieldDef] = [
    FieldDef("DEFAULT_LLM_PROVIDER", "Провайдер за замовчуванням", placeholder="openai"),
    FieldDef("SEARCH_GEMINI_MODEL", "Gemini модель для пошуку", placeholder="gemini-2.5-flash"),
    FieldDef("SEARCH_OPENAI_MODEL", "OpenAI модель для grounded fallback", placeholder="gpt-5"),
    FieldDef("SEARCH_PROFILE_GENERAL_ORDER", "Search order: general"),
    FieldDef("SEARCH_PROFILE_NEWS_ORDER", "Search order: news"),
    FieldDef("SEARCH_PROFILE_DOCS_ORDER", "Search order: docs"),
    FieldDef("SEARCH_PROFILE_RESEARCH_PAPER_ORDER", "Search order: research paper"),
]

VOICE_FIELDS: list[FieldDef] = [
    FieldDef(
        "OPENAI_WHISPER_MODEL",
        "Whisper модель (STT)",
        placeholder="whisper-1",
        help_text="Транскрипція голосу. Працює окремо від stt_voice capability.",
    ),
    FieldDef(
        "OPENAI_TTS_MODEL",
        "TTS модель (синтез)",
        placeholder="gpt-4o-mini-tts",
    ),
    FieldDef(
        "OPENAI_VOCALIZER_VOICE",
        "Голос TTS",
        placeholder="alloy",
        help_text="alloy / echo / fable / onyx / nova / shimmer",
    ),
]

TUNING_FIELDS: list[FieldDef] = [
    FieldDef(
        "MEMORY_CONTEXT_BUDGET",
        "Total memory context budget (tokens)",
        placeholder="10000",
        help_text="Загальний ліміт пам'яті, яку можна додати до prompt після резерву під поточні повідомлення.",
    ),
    FieldDef(
        "MEMORY_WORKING_CONTEXT_BUDGET",
        "Working memory context budget (tokens)",
        placeholder="5000",
        help_text="Скільки токенів recent/working пам'яті можна показати моделі у поточному turn.",
    ),
    FieldDef(
        "MEMORY_LONG_CONTEXT_BUDGET",
        "Long-term context budget (tokens)",
        placeholder="4000",
        help_text="Скільки токенів long-term пам'яті можна повернути у prompt.",
    ),
    FieldDef(
        "MEMORY_CORE_CONTEXT_BUDGET",
        "Core context budget (tokens)",
        placeholder="1000",
        help_text="Скільки токенів core-фактів і beliefs можна повернути у prompt.",
    ),
    FieldDef(
        "MEMORY_RECENT_BUDGET",
        "Recent memory compression budget (tokens)",
        placeholder="5000",
        help_text="Коли recent/working шар перевищує цей ліміт, він стискається у long-term.",
    ),
    FieldDef(
        "MEMORY_LONG_BUDGET",
        "Long-term storage budget (tokens)",
        placeholder="30000",
        help_text="Скільки long-term пам'яті зберігати перед каскадним перестисненням.",
    ),
    FieldDef(
        "MEMORY_CORE_BUDGET",
        "Core storage budget (tokens)",
        placeholder="1000",
        help_text="Ліміт core-шару пам'яті у сховищі.",
    ),
    FieldDef(
        "ALBUM_PROCESSING_SETTLE_SECONDS",
        "Album collect window (s)",
        placeholder="6.0",
        help_text="Скільки чекати, поки прийдуть всі sibling-айтеми альбому.",
    ),
    FieldDef(
        "MEDIA_TMP_MAX_AGE_HOURS",
        "Media tmp TTL (hours)",
        placeholder="24",
        help_text="Файли старші за цей TTL чистяться scheduler job-ом.",
    ),
]

ACCESS_FIELDS: list[FieldDef] = [
    FieldDef("SMARTEST_ADMIN_USERNAME", "Логін панелі"),
    FieldDef("SMARTEST_ADMIN_PASSWORD", "Пароль панелі", input_type="password",
             help_text="Після зміни новий логін/пароль застосуються для наступних входів."),
]

# ---------------------------------------------------------------------------
# Helpers: env read / write
# ---------------------------------------------------------------------------

def _admin_password_key() -> str:
    return "SMARTEST_ADMIN_PASSWORD"

def _admin_username_key() -> str:
    return "SMARTEST_ADMIN_USERNAME"

def _session_secret_key() -> str:
    return "SMARTEST_ADMIN_SESSION_SECRET"

def _safe_env_value(raw: str) -> str:
    value = str(raw)
    if value == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./:@?&=%+,\-]+", value):
        return value
    return json.dumps(value, ensure_ascii=False)

def _parse_env_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        # Values written by _safe_env_value use json.dumps, so parse back with json.loads
        try:
            return json.loads(value)
        except Exception:
            pass
        # Fallback: strip quotes
        return value[1:-1]
    return value

def read_env_lines(path: Path) -> list[EnvLine]:
    if not path.exists():
        return []
    lines: list[EnvLine] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            lines.append(EnvLine(kind="blank", raw=raw_line))
            continue
        if stripped.startswith("#") or "=" not in raw_line:
            lines.append(EnvLine(kind="comment", raw=raw_line))
            continue
        key, raw_value = raw_line.split("=", 1)
        key = key.strip()
        lines.append(EnvLine(kind="entry", raw=raw_line, key=key, value=_parse_env_value(raw_value)))
    return lines

def env_map_from_lines(lines: Iterable[EnvLine]) -> dict[str, str]:
    return {line.key: line.value for line in lines if line.kind == "entry" and line.key}

def write_env_updates(path: Path, updates: dict[str, str]) -> None:
    lines = read_env_lines(path)
    if not lines and path.exists():
        lines = []
    remaining = dict(updates)
    rendered: list[str] = []
    for line in lines:
        if line.kind != "entry" or not line.key:
            rendered.append(line.raw)
            continue
        if line.key in remaining:
            rendered.append(f"{line.key}={_safe_env_value(remaining.pop(line.key))}")
        else:
            rendered.append(line.raw)
    if remaining:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append("# Admin UI managed")
        for key, value in remaining.items():
            rendered.append(f"{key}={_safe_env_value(value)}")
    path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")

# ---------------------------------------------------------------------------
# Helpers: auth
# ---------------------------------------------------------------------------

def ensure_session_secret(values: dict[str, str]) -> str:
    secret = values.get(_session_secret_key()) or ""
    if secret:
        return secret
    secret = secrets.token_urlsafe(32)
    write_env_updates(ENV_PATH, {_session_secret_key(): secret})
    return secret

def admin_username(values: dict[str, str]) -> str:
    return values.get(_admin_username_key()) or os.getenv(_admin_username_key()) or "admin"

def admin_password(values: dict[str, str]) -> str:
    return values.get(_admin_password_key()) or os.getenv(_admin_password_key()) or "admin"

def session_token(username: str, secret: str) -> str:
    payload = {"u": username, "exp": int(time.time()) + SESSION_MAX_AGE}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{encoded}.{digest}"

def parse_session_token(token: str, secret: str) -> dict | None:
    try:
        encoded, digest = token.split(".", 1)
    except ValueError:
        return None
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception:
        return None
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) <= int(time.time()):
        return None
    return payload

# ---------------------------------------------------------------------------
# Helpers: systemctl
# ---------------------------------------------------------------------------

def systemctl_text(*args: str) -> str:
    try:
        proc = subprocess.run(["systemctl", *args], check=False, capture_output=True, text=True, timeout=15)
    except Exception as exc:
        logger.warning("admin.systemctl_failed args=%s error=%s", args, exc)
        return "unknown"
    return (proc.stdout or proc.stderr or "unknown").strip()

def service_status(service_name: str) -> str:
    return systemctl_text("is-active", service_name) or "unknown"

def restart_service(service_name: str) -> tuple[bool, str]:
    output = systemctl_text("restart", service_name)
    ok = service_status(service_name) == "active"
    return ok, output


def clear_bot_memory() -> tuple[bool, str]:
    try:
        asyncio.run(memory_manager.clear_global())
    except Exception as exc:
        logger.exception("admin.clear_memory_failed error=%s", exc)
        return False, str(exc)
    logger.info("admin.clear_memory_ok")
    return True, "ok"


def _fmt_int(value: object) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", " ")
    except Exception:
        return "0"


async def _fetch_memory_token_dashboard() -> dict[str, object]:
    from db.connection import close_db, fetchall, fetchone

    async def total(table: str) -> dict:
        return await fetchone(
            f"SELECT COUNT(*) AS rows_count, COALESCE(SUM(tokens), 0) AS tokens FROM {table}"
        ) or {"rows_count": 0, "tokens": 0}

    try:
        recent = await total("memory_recent")
        long = await total("memory_long")
        core = await total("memory_core")
        chats = await fetchall(
            """
            SELECT
              ids.chat_id,
              COALESCE(r.rows_count, 0) AS recent_rows,
              COALESCE(r.tokens, 0) AS recent_tokens,
              COALESCE(l.rows_count, 0) AS long_rows,
              COALESCE(l.tokens, 0) AS long_tokens,
              COALESCE(c.rows_count, 0) AS core_rows,
              COALESCE(c.tokens, 0) AS core_tokens,
              COALESCE(r.tokens, 0) + COALESCE(l.tokens, 0) + COALESCE(c.tokens, 0) AS total_tokens
            FROM (
              SELECT chat_id FROM memory_recent
              UNION
              SELECT chat_id FROM memory_long
              UNION
              SELECT chat_id FROM memory_core
            ) ids
            LEFT JOIN (
              SELECT chat_id, COUNT(*) AS rows_count, COALESCE(SUM(tokens), 0) AS tokens
              FROM memory_recent
              GROUP BY chat_id
            ) r ON r.chat_id = ids.chat_id
            LEFT JOIN (
              SELECT chat_id, COUNT(*) AS rows_count, COALESCE(SUM(tokens), 0) AS tokens
              FROM memory_long
              GROUP BY chat_id
            ) l ON l.chat_id = ids.chat_id
            LEFT JOIN (
              SELECT chat_id, COUNT(*) AS rows_count, COALESCE(SUM(tokens), 0) AS tokens
              FROM memory_core
              GROUP BY chat_id
            ) c ON c.chat_id = ids.chat_id
            ORDER BY total_tokens DESC
            LIMIT 20
            """
        ) or []
        return {
            "recent": recent,
            "long": long,
            "core": core,
            "chats": chats,
            "total_tokens": int(recent.get("tokens") or 0)
            + int(long.get("tokens") or 0)
            + int(core.get("tokens") or 0),
        }
    finally:
        await close_db()


def token_dashboard_data() -> dict[str, object]:
    from core.token_usage import read_usage_events, summarize_usage_events, token_usage_log_path

    usage = summarize_usage_events(read_usage_events())
    try:
        memory = asyncio.run(_fetch_memory_token_dashboard())
        memory_error = ""
    except Exception as exc:
        memory = {
            "recent": {"rows_count": 0, "tokens": 0},
            "long": {"rows_count": 0, "tokens": 0},
            "core": {"rows_count": 0, "tokens": 0},
            "chats": [],
            "total_tokens": 0,
        }
        memory_error = str(exc)
    return {
        "usage": usage,
        "memory": memory,
        "memory_error": memory_error,
        "log_path": str(token_usage_log_path()),
    }


def read_current_config() -> dict[str, str]:
    return env_map_from_lines(read_env_lines(ENV_PATH))

def capability_field_key(slug: str, suffix: str) -> str:
    return f"CAPABILITY_{slug.upper()}_{suffix}"

# ---------------------------------------------------------------------------
# Resolve effective values (what the bot ACTUALLY uses)
# ---------------------------------------------------------------------------

def _effective_provider(cap: CapabilityDef, values: dict[str, str]) -> str:
    key = capability_field_key(cap.slug, "PROVIDER")
    return values.get(key, "").strip() or values.get("DEFAULT_LLM_PROVIDER", "").strip() or cap.default_provider

def _effective_model(cap: CapabilityDef, values: dict[str, str]) -> str:
    key = capability_field_key(cap.slug, "MODEL")
    v = values.get(key, "").strip()
    if v:
        return v
    # Resolve through legacy fallbacks same way core/env.py does
    slug_upper = cap.slug.upper()
    if slug_upper == "PLANNER_REASONING":
        return values.get("OPENAI_PLANNER_MODEL", "") or values.get("OPENAI_CHAT_MODEL", "") or values.get("OPENAI_GPT_MODEL", "") or cap.default_model
    if slug_upper == "VISION_IMAGE":
        return values.get("OPENAI_VISION_MODEL", "") or values.get("VISION_MODEL", "") or values.get("OPENAI_CHAT_MODEL", "") or values.get("OPENAI_GPT_MODEL", "") or cap.default_model
    if slug_upper == "MEMORY_SUMMARY":
        return values.get("OPENAI_SUMMARIZER_MODEL", "") or values.get("OPENAI_CHAT_MODEL", "") or values.get("OPENAI_GPT_MODEL", "") or cap.default_model
    return values.get("OPENAI_CHAT_MODEL", "") or values.get("OPENAI_GPT_MODEL", "") or cap.default_model

# ---------------------------------------------------------------------------
# Rendering: dashboard
# ---------------------------------------------------------------------------

def _render_field_grid(fields: list[FieldDef], values: dict[str, str], *, item_class: str = "adv-label") -> str:
    out = ""
    for f in fields:
        value = html.escape(values.get(f.key, "") or f.placeholder)
        placeholder = html.escape(f.placeholder)
        help_html = f'<p class="field-help">{html.escape(f.help_text)}</p>' if f.help_text else ""
        out += (
            f'<label class="{item_class}">{html.escape(f.label)}'
            f'<input class="inp" type="{html.escape(f.input_type)}" '
            f'name="{html.escape(f.key)}" value="{value}" placeholder="{placeholder}">'
            f'{help_html}</label>'
        )
    return out


def render_dashboard(values: dict[str, str], flash: str = "", flash_kind: str = "info") -> str:
    bot_status = service_status(MANAGED_BOT_SERVICE)
    admin_status = service_status(SELF_SERVICE_NAME)
    env_mtime = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ENV_PATH.stat().st_mtime))
        if ENV_PATH.exists() else "-"
    )
    flash_html = (
        f'<div class="flash flash-{html.escape(flash_kind)}">{html.escape(flash)}</div>'
        if flash else ""
    )
    token_data = token_dashboard_data()
    usage = token_data.get("usage") or {}
    memory = token_data.get("memory") or {}
    log_path = html.escape(str(token_data.get("log_path") or ""))

    usage_rows = ""
    for row in usage.get("by_model") or []:
        usage_rows += f"""<tr>
          <td>{html.escape(str(row.get("provider") or "unknown"))}</td>
          <td>{html.escape(str(row.get("model") or "unknown"))}</td>
          <td>{html.escape(str(row.get("capability") or "unknown"))}</td>
          <td>{_fmt_int(row.get("calls"))}</td>
          <td>{_fmt_int(row.get("failed"))}</td>
          <td>{_fmt_int(row.get("tokens_in"))}</td>
          <td>{_fmt_int(row.get("tokens_out"))}</td>
          <td>{_fmt_int(row.get("tokens_total"))}</td>
        </tr>"""
    if not usage_rows:
        usage_rows = '<tr><td colspan="8" class="muted-cell">No tracked LLM calls yet. The table starts filling after the next bot responses.</td></tr>'

    chat_rows = ""
    for row in memory.get("chats") or []:
        chat_rows += f"""<tr>
          <td>{html.escape(str(row.get("chat_id") or ""))}</td>
          <td>{_fmt_int(row.get("recent_tokens"))}</td>
          <td>{_fmt_int(row.get("long_tokens"))}</td>
          <td>{_fmt_int(row.get("core_tokens"))}</td>
          <td>{_fmt_int(row.get("total_tokens"))}</td>
        </tr>"""
    if not chat_rows:
        chat_rows = '<tr><td colspan="5" class="muted-cell">No memory rows found yet.</td></tr>'

    recent = memory.get("recent") or {}
    long = memory.get("long") or {}
    core = memory.get("core") or {}
    memory_error = str(token_data.get("memory_error") or "")
    memory_error_html = (
        f'<p class="token-warning">Memory token query failed: {html.escape(memory_error)}</p>'
        if memory_error else ""
    )
    token_panel_html = f"""<section class="panel token-panel">
      <div class="token-head">
        <div>
          <h2>Token calculator</h2>
          <p class="panel-desc">Tracks all future LLM calls by provider/model/capability and shows the current memory context already stored in the production DB.</p>
        </div>
        <div class="token-log">Usage log: <code>{log_path}</code></div>
      </div>
      <div class="token-grid">
        <div class="token-stat"><span>LLM calls</span><strong>{_fmt_int(usage.get("calls"))}</strong></div>
        <div class="token-stat"><span>Failed calls</span><strong>{_fmt_int(usage.get("failed"))}</strong></div>
        <div class="token-stat"><span>Input tokens</span><strong>{_fmt_int(usage.get("tokens_in"))}</strong></div>
        <div class="token-stat"><span>Output tokens</span><strong>{_fmt_int(usage.get("tokens_out"))}</strong></div>
        <div class="token-stat"><span>Total tracked</span><strong>{_fmt_int(usage.get("tokens_total"))}</strong></div>
      </div>
      <div class="token-table-wrap">
        <h3>Tracked LLM calls by model</h3>
        <table class="usage-table">
          <thead><tr><th>Provider</th><th>Model</th><th>Capability</th><th>Calls</th><th>Failed</th><th>Input</th><th>Output</th><th>Total</th></tr></thead>
          <tbody>{usage_rows}</tbody>
        </table>
      </div>
      <div class="token-grid memory-grid">
        <div class="token-stat"><span>Recent memory</span><strong>{_fmt_int(recent.get("tokens"))}</strong><em>{_fmt_int(recent.get("rows_count"))} rows</em></div>
        <div class="token-stat"><span>Long memory</span><strong>{_fmt_int(long.get("tokens"))}</strong><em>{_fmt_int(long.get("rows_count"))} rows</em></div>
        <div class="token-stat"><span>Core memory</span><strong>{_fmt_int(core.get("tokens"))}</strong><em>{_fmt_int(core.get("rows_count"))} rows</em></div>
        <div class="token-stat"><span>Stored context total</span><strong>{_fmt_int(memory.get("total_tokens"))}</strong></div>
      </div>
      {memory_error_html}
      <div class="token-table-wrap">
        <h3>Working memory context by chat</h3>
        <table class="usage-table">
          <thead><tr><th>Chat</th><th>Recent</th><th>Long</th><th>Core</th><th>Total</th></tr></thead>
          <tbody>{chat_rows}</tbody>
        </table>
      </div>
    </section>"""

    # Which providers have keys?
    providers_with_keys: set[str] = set()
    for p in PROVIDERS:
        if values.get(p.key_env, "").strip():
            providers_with_keys.add(p.slug)

    # --- Provider key cards ---
    def _provider_cards(provs: list[ProviderDef]) -> str:
        out = ""
        for p in provs:
            has_key = p.slug in providers_with_keys
            dot = "dot-ok" if has_key else "dot-empty"
            kv = html.escape(values.get(p.key_env, ""))
            out += f'''<div class="prov-card">
              <div class="prov-header"><span class="dot {dot}"></span><strong>{html.escape(p.label)}</strong></div>
              <p class="prov-hint">{html.escape(p.help_text)}</p>
              <div class="prov-key-row">
                <input class="secret-input prov-key-input" type="password" name="{html.escape(p.key_env)}" value="{kv}" data-provider="{p.slug}" placeholder="API key">
                <button class="btn-eye" type="button" data-toggle-secret>&#128065;</button>
              </div>
            </div>'''
        return out

    llm_cards = _provider_cards(LLM_PROVIDERS)

    # Search provider cards with info tooltips
    search_cards = ""
    for p in SEARCH_PROVIDERS:
        has_key = p.slug in providers_with_keys
        dot = "dot-ok" if has_key else "dot-empty"
        kv = html.escape(values.get(p.key_env, ""))
        info = SEARCH_PROVIDER_INFO.get(p.slug, "")
        info_btn = f'<button type="button" class="info-btn" title="{html.escape(info)}">i</button>' if info else ""
        search_cards += f'''<div class="prov-card">
          <div class="prov-header"><span class="dot {dot}"></span><strong>{html.escape(p.label)}</strong>{info_btn}</div>
          <p class="prov-hint">{html.escape(p.help_text)}</p>
          <div class="prov-key-row">
            <input class="secret-input prov-key-input" type="password" name="{html.escape(p.key_env)}" value="{kv}" data-provider="{p.slug}" placeholder="API key">
            <button class="btn-eye" type="button" data-toggle-secret>&#128065;</button>
          </div>
        </div>'''

    # --- Default search provider selector ---
    current_search_prov = (values.get("SEARCH_PROVIDER", "") or "auto").strip().lower()
    search_prov_opts = '<option value="auto"' + (' selected' if current_search_prov == "auto" else '') + '>Авто (за пріоритетом)</option>'
    for p in SEARCH_PROVIDERS:
        sel = " selected" if p.slug == current_search_prov else ""
        has = p.slug in providers_with_keys
        dis = "" if has else ' disabled'
        tag = "" if has else " (немає ключа)"
        search_prov_opts += f'<option value="{p.slug}"{sel}{dis}>{html.escape(p.label)}{tag}</option>'

    # --- Capability group cards ---
    models_json = json.dumps(MODELS, ensure_ascii=False)

    groups_html = ""
    for group_id, group_title, group_desc in CAPABILITY_GROUPS:
        caps = [c for c in CAPABILITIES if c.group == group_id]
        cards = ""
        for cap in caps:
            eff_provider = _effective_provider(cap, values)
            eff_model = _effective_model(cap, values)
            custom_key_env = capability_field_key(cap.slug, "API_KEY")
            has_custom_key = bool(values.get(custom_key_env, "").strip())
            custom_key_val = html.escape(values.get(custom_key_env, ""))

            # Provider: <select> with only LLM providers that have keys (+ current even if no key)
            valid_providers_for_type = set(MODELS.get(cap.model_type, MODELS["text"]).keys())
            prov_opts = ""
            for lp in LLM_PROVIDERS:
                if lp.slug not in valid_providers_for_type:
                    continue
                sel = " selected" if lp.slug == eff_provider else ""
                dis = "" if (lp.slug in providers_with_keys or lp.slug == eff_provider) else ' disabled class="no-key"'
                tag = "" if lp.slug in providers_with_keys else " (немає ключа)"
                prov_opts += f'<option value="{lp.slug}"{sel}{dis}>{html.escape(lp.label)}{tag}</option>'

            # Model: always <select>
            provider_models = MODELS.get(cap.model_type, MODELS.get("text", {})).get(eff_provider, [])
            model_el = f'<select class="inp cap-model" name="{capability_field_key(cap.slug, "MODEL")}" data-cap="{cap.slug}">'
            found = False
            for m in provider_models:
                sel = ""
                if m == eff_model:
                    sel = " selected"
                    found = True
                model_el += f'<option value="{m}"{sel}>{m}</option>'
            if not found and eff_model:
                model_el += f'<option value="{html.escape(eff_model)}" selected>{html.escape(eff_model)}</option>'
            model_el += "</select>"

            # Hidden fields: provider env key, adapter (auto-computed)
            adapter_val = _auto_adapter(eff_provider, cap.model_type)
            hidden_adapter = f'<input type="hidden" name="{capability_field_key(cap.slug, "ADAPTER")}" value="{html.escape(adapter_val)}" class="cap-adapter">'

            # Custom key section
            ck_checked = " checked" if has_custom_key else ""
            ck_display = "" if has_custom_key else ' style="display:none"'

            cards += f'''<div class="cap-card" data-cap="{cap.slug}" data-model-type="{cap.model_type}">
              <div class="cap-top">
                <h3>{html.escape(cap.title)}</h3>
                <span class="badge">{html.escape(cap.recommendation)}</span>
              </div>
              <p class="cap-desc">{html.escape(cap.help_text)}</p>
              <div class="cap-fields">
                <label class="cap-label">Провайдер
                  <select class="inp cap-provider" name="{capability_field_key(cap.slug, "PROVIDER")}" data-cap="{cap.slug}">
                    {prov_opts}
                  </select>
                </label>
                <label class="cap-label">Модель
                  {model_el}
                </label>
              </div>
              {hidden_adapter}
              <label class="ck-toggle"><input type="checkbox" class="ck-check" data-cap="{cap.slug}"{ck_checked}> Окремий API ключ</label>
              <div class="ck-field" data-cap="{cap.slug}"{ck_display}>
                <div class="prov-key-row">
                  <input class="secret-input" type="password" name="{html.escape(custom_key_env)}" value="{custom_key_val}" placeholder="Окремий ключ для цього агента">
                  <button class="btn-eye" type="button" data-toggle-secret>&#128065;</button>
                </div>
              </div>
            </div>'''

        groups_html += f'''<section class="panel">
          <h2>{html.escape(group_title)}</h2>
          <p class="panel-desc">{html.escape(group_desc)}</p>
          <div class="cap-grid">{cards}</div>
        </section>'''

    # --- Advanced (collapsed) ---
    voice_fields = _render_field_grid(VOICE_FIELDS, values)
    tuning_fields = _render_field_grid(TUNING_FIELDS, values)
    adv_fields = _render_field_grid(GLOBAL_FIELDS, values)

    return f"""<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smartest Control</title>
<style>
:root {{
  --bg: #f3ead9; --paper: rgba(255,248,236,0.88); --ink: #1f1d19;
  --muted: #655d4d; --line: rgba(59,45,30,0.14); --accent: #bf4b2c;
  --accent2: #204d46; --ok: #2c6b44; --warn: #935a14;
  --sh: 0 24px 60px rgba(52,36,18,0.12);
}}
*{{ box-sizing:border-box; }}
body{{ margin:0; min-height:100vh; font-family:"IBM Plex Sans","Segoe UI",sans-serif; color:var(--ink);
  background: radial-gradient(circle at top left,rgba(191,75,44,.22),transparent 32%),
    radial-gradient(circle at bottom right,rgba(32,77,70,.18),transparent 28%),
    linear-gradient(135deg,#efe1c4 0%,#f7f0e3 42%,#e8dcc5 100%);
}}
.sh{{ max-width:1480px; margin:0 auto; padding:28px 18px 48px; }}

/* Hero */
.hero{{ display:grid; gap:18px; grid-template-columns:1.2fr .8fr; align-items:end; margin-bottom:24px; }}
.hero-card,.st-card,.panel,.cap-card,.prov-card{{
  background:var(--paper); backdrop-filter:blur(12px);
  border:1px solid var(--line); border-radius:24px; box-shadow:var(--sh);
}}
.hero-card{{ padding:28px; }}
.hero-card h1{{ margin:0 0 10px; font-size:clamp(2rem,4vw,3.4rem); line-height:.95; letter-spacing:-.04em; }}
.hero-card p{{ margin:0; color:var(--muted); max-width:62ch; }}
.st-grid{{ display:grid; gap:14px; grid-template-columns:1fr 1fr; }}
.st-card{{ padding:20px; }}
.st-lbl{{ display:block; color:var(--muted); font-size:.82rem; text-transform:uppercase; letter-spacing:.14em; margin-bottom:8px; }}
.st-val{{ font-size:1.2rem; font-weight:700; }}
.st-ok{{ color:var(--ok); }} .st-warn{{ color:var(--warn); }}

/* Flash */
.flash{{ margin-bottom:20px; padding:14px 16px; border-radius:16px; font-weight:600; }}
.flash-info{{ background:rgba(32,77,70,.12); color:var(--accent2); border:1px solid rgba(32,77,70,.18); }}
.flash-error{{ background:rgba(191,75,44,.12); color:#8b2e14; border:1px solid rgba(191,75,44,.18); }}

/* Toolbar */
.toolbar{{ display:flex; gap:12px; flex-wrap:wrap; justify-content:space-between; align-items:center; margin-bottom:18px; }}
.toolbar-left,.toolbar-right{{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
.btn{{ border:0; border-radius:999px; padding:14px 20px; font:inherit; font-weight:700; cursor:pointer; transition:transform .16s; }}
.btn:hover{{ transform:translateY(-1px); }}
.btn-main{{ color:#fff7ef; background:linear-gradient(135deg,var(--accent),#d96c44); }}
.btn-sec{{ color:var(--ink); background:rgba(255,255,255,.7); border:1px solid var(--line); }}
.chk{{ display:inline-flex; gap:10px; align-items:center; color:var(--muted); font-weight:600; }}
.muted{{ color:var(--muted); font-size:.94rem; }}

/* Panel */
.panel{{ padding:22px; margin-bottom:20px; }}
.panel h2{{ margin:0 0 8px; font-size:1.15rem; }}
.panel-desc{{ margin:0 0 16px; color:var(--muted); line-height:1.5; }}

/* Token calculator */
.token-head{{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap; }}
.token-log{{ color:var(--muted); font-size:.82rem; max-width:560px; word-break:break-all; }}
.token-grid{{ display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); margin:14px 0 18px; }}
.token-stat{{ border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.54); padding:14px; }}
.token-stat span{{ display:block; color:var(--muted); font-size:.82rem; margin-bottom:6px; }}
.token-stat strong{{ display:block; font-size:1.42rem; line-height:1.1; }}
.token-stat em{{ display:block; color:var(--muted); font-size:.8rem; margin-top:4px; font-style:normal; }}
.memory-grid{{ margin-top:20px; }}
.token-table-wrap{{ overflow:auto; margin-top:12px; }}
.token-table-wrap h3{{ margin:0 0 10px; font-size:1rem; }}
.usage-table{{ width:100%; border-collapse:collapse; min-width:760px; font-size:.9rem; }}
.usage-table th,.usage-table td{{ border-bottom:1px solid var(--line); padding:10px 9px; text-align:left; white-space:nowrap; }}
.usage-table th{{ color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; }}
.muted-cell{{ color:var(--muted); }}
.token-warning{{ color:var(--warn); margin:10px 0 0; }}

/* Provider cards */
.prov-grid{{ display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }}
.prov-card{{ padding:16px; border-radius:20px; }}
.prov-header{{ display:flex; align-items:center; gap:8px; margin-bottom:6px; }}
.prov-hint{{ margin:0 0 10px; color:var(--muted); font-size:.85rem; }}
.info-btn{{
  display:inline-flex; align-items:center; justify-content:center;
  width:20px; height:20px; border-radius:50%; border:1.5px solid var(--accent2);
  background:transparent; color:var(--accent2); font-size:.75rem; font-weight:700;
  font-style:italic; cursor:help; margin-left:6px; padding:0; flex-shrink:0;
}}
.dot{{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}
.dot-ok{{ background:var(--ok); box-shadow:0 0 6px rgba(44,107,68,.4); }}
.dot-empty{{ background:var(--line); }}
.prov-key-row{{ display:flex; gap:8px; align-items:center; }}
.prov-key-row input{{ flex:1; }}
.search-default-row{{ margin-bottom:16px; max-width:360px; }}

/* Capability cards */
.cap-grid{{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); }}
.cap-card{{ padding:18px; animation:rise .35s ease both; }}
.cap-top{{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:4px; }}
.cap-top h3{{ margin:0; font-size:1rem; }}
.badge{{
  display:inline-block; padding:3px 10px; border-radius:999px;
  font-size:.76rem; font-weight:600; background:rgba(32,77,70,.1); color:var(--accent2);
}}
.cap-desc{{ margin:0 0 12px; color:var(--muted); font-size:.9rem; line-height:1.4; }}
.cap-fields{{ display:grid; gap:12px; grid-template-columns:1fr 1fr; }}
.cap-label{{ display:block; font-weight:700; font-size:.88rem; }}
.cap-label select,.cap-label input{{ margin-top:6px; }}

/* Inputs */
.inp,.secret-input{{
  width:100%; border:1px solid rgba(59,45,30,.18); border-radius:14px;
  background:rgba(255,255,255,.82); padding:11px 14px; font:inherit; color:var(--ink);
}}
select.inp{{ appearance:auto; }}
option.no-key{{ color:#bbb; }}
.btn-eye{{
  border:1px solid rgba(59,45,30,.18); background:rgba(255,255,255,.7);
  color:var(--ink); padding:10px 12px; border-radius:14px; font:inherit; cursor:pointer; flex-shrink:0;
}}

/* Custom key */
.ck-toggle{{
  display:flex; align-items:center; gap:8px; margin-top:12px;
  color:var(--muted); font-size:.85rem; cursor:pointer;
}}
.ck-toggle input{{ width:auto; }}
.ck-field{{ margin-top:8px; }}

/* Advanced */
.adv-toggle{{ cursor:pointer; color:var(--accent2); font-weight:600; margin-bottom:12px; display:block; }}
.adv-body{{ display:none; }}
.adv-body.open{{ display:block; }}
.adv-grid{{ display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }}
.adv-label{{ display:block; font-weight:700; font-size:.88rem; }}
.adv-label input{{ margin-top:6px; }}
.field-help{{ margin:6px 0 0; color:var(--muted); font-size:.8rem; line-height:1.35; font-weight:500; }}

/* Access */
.acc-grid{{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }}
.acc-label{{ display:block; font-weight:700; font-size:.88rem; }}
.acc-label input{{ margin-top:6px; }}
.acc-help{{ margin:6px 0 0; color:var(--muted); font-size:.83rem; }}

@keyframes rise{{ from{{ opacity:0; transform:translateY(8px); }} to{{ opacity:1; transform:translateY(0); }} }}
@media(max-width:980px){{ .hero{{ grid-template-columns:1fr; }} .st-grid{{ grid-template-columns:1fr 1fr; }} }}
@media(max-width:620px){{
  .sh{{ padding:18px 14px 34px; }} .st-grid{{ grid-template-columns:1fr; }}
  .cap-fields{{ grid-template-columns:1fr; }} .toolbar{{ align-items:stretch; }}
}}
</style>
</head>
<body>
<div class="sh">
  <section class="hero">
    <div class="hero-card">
      <h1>Smartest Control</h1>
      <p>Конфігурація бота: API ключі і моделі для кожного агента.</p>
    </div>
    <div class="st-grid">
      <div class="st-card"><span class="st-lbl">Bot</span><div class="st-val {"st-ok" if bot_status=="active" else "st-warn"}">{html.escape(bot_status)}</div></div>
      <div class="st-card"><span class="st-lbl">Admin</span><div class="st-val {"st-ok" if admin_status=="active" else "st-warn"}">{html.escape(admin_status)}</div></div>
      <div class="st-card"><span class="st-lbl">Env</span><div class="st-val">{html.escape(env_mtime)}</div></div>
      <div class="st-card"><span class="st-lbl">Service</span><div class="st-val">{html.escape(MANAGED_BOT_SERVICE)}</div></div>
    </div>
  </section>
  {flash_html}
  {token_panel_html}
  <form method="post" action="/save">
    <div class="toolbar">
      <div class="toolbar-left">
        <button class="btn btn-main" type="submit">Зберегти і перезапустити</button>
        <label class="chk"><input type="checkbox" name="restart_bot" value="1" checked> Перезапустити бота</label>
      </div>
      <div class="toolbar-right">
        <a class="btn btn-sec" href="/prompts">Промпти</a>
        <a class="btn btn-sec" href="/logs">Логи</a>
        <button class="btn btn-sec" type="submit" formaction="/logout" formmethod="post">Вийти</button>
        <button class="btn btn-sec" type="submit" formaction="/clear-memory" formmethod="post" onclick="return confirm('Очистити всю пам\\'ять бота? Це видалить recent, long-term і core пам\\'ять для всіх чатів.');">Очистити пам'ять</button>
      </div>
    </div>

    <!-- LLM Providers -->
    <section class="panel">
      <h2>LLM Провайдери</h2>
      <p class="panel-desc">Введіть API ключі. Агенти нижче можуть використовувати тільки провайдерів з ключами.</p>
      <div class="prov-grid">{llm_cards}</div>
    </section>

    <!-- Search Providers -->
    <section class="panel">
      <h2>Search Провайдери</h2>
      <p class="panel-desc">Пошукові API. Введіть ключ і виберіть основний пошуковик.</p>
      <div class="search-default-row">
        <label class="cap-label">Пошуковик за замовчуванням
          <select class="inp" name="SEARCH_PROVIDER" id="search-default-select">
            {search_prov_opts}
          </select>
        </label>
      </div>
      <div class="prov-grid">{search_cards}</div>
    </section>

    <!-- Voice and STT -->
    <section class="panel">
      <h2>Voice & STT</h2>
      <p class="panel-desc">Реальні runtime-ключі для транскрипції голосу і синтезу аудіовідповідей. Це не вибір чат-моделі для stt_voice.</p>
      <div class="adv-grid">{voice_fields}</div>
    </section>

    <!-- Memory and albums -->
    <section class="panel">
      <h2>Memory & Albums</h2>
      <p class="panel-desc">Бюджети пам'яті, вікно збору Telegram-альбомів і TTL тимчасових медіафайлів.</p>
      <div class="adv-grid">{tuning_fields}</div>
    </section>

    <!-- Agent groups -->
    {groups_html}

    <!-- Advanced (collapsed) -->
    <section class="panel">
      <span class="adv-toggle" id="adv-toggle">&#9660; Розширені налаштування</span>
      <div class="adv-body" id="adv-body">
        <div class="adv-grid">{adv_fields}</div>
      </div>
    </section>

    <!-- Access -->
    <section class="panel">
      <h2>Доступ</h2>
      <div class="acc-grid">
        <label class="acc-label">Логін<input class="inp" type="text" name="SMARTEST_ADMIN_USERNAME" value="{html.escape(values.get('SMARTEST_ADMIN_USERNAME', ''))}"></label>
        <label class="acc-label">Пароль
          <div class="prov-key-row"><input class="secret-input" type="password" name="SMARTEST_ADMIN_PASSWORD" value="{html.escape(values.get('SMARTEST_ADMIN_PASSWORD', ''))}"><button class="btn-eye" type="button" data-toggle-secret>&#128065;</button></div>
          <p class="acc-help">Після зміни новий пароль працюватиме з наступного входу.</p>
        </label>
      </div>
    </section>
  </form>
</div>

<script>
const MODELS = {models_json};

// Toggle password visibility
document.querySelectorAll('[data-toggle-secret]').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const inp = btn.closest('.prov-key-row, .field-control')?.querySelector('input') || btn.parentElement.querySelector('input');
    if (!inp) return;
    inp.type = inp.type === 'password' ? 'text' : 'password';
  }});
}});

// Advanced toggle
document.getElementById('adv-toggle')?.addEventListener('click', () => {{
  document.getElementById('adv-body')?.classList.toggle('open');
}});

// Custom key checkbox
document.querySelectorAll('.ck-check').forEach(cb => {{
  cb.addEventListener('change', () => {{
    const f = document.querySelector('.ck-field[data-cap="'+cb.dataset.cap+'"]');
    if (f) {{ f.style.display = cb.checked ? '' : 'none'; if (!cb.checked) {{ const i = f.querySelector('input'); if(i) i.value=''; }} }}
  }});
}});

// Which providers have keys
function activeProviders() {{
  const s = new Set();
  document.querySelectorAll('.prov-key-input').forEach(i => {{ if(i.value.trim()) s.add(i.dataset.provider); }});
  return s;
}}

// Update provider dropdowns when keys change
function refreshProviderDropdowns() {{
  const active = activeProviders();
  document.querySelectorAll('.cap-provider').forEach(sel => {{
    const cur = sel.value;
    Array.from(sel.options).forEach(opt => {{
      opt.disabled = !active.has(opt.value) && opt.value !== cur;
      opt.textContent = opt.textContent.replace(/ \\(немає ключа\\)$/, '');
      if (opt.disabled && opt.value !== cur) opt.textContent += ' (немає ключа)';
    }});
  }});
}}

// Update model list when provider changes
function refreshModels(sel) {{
  const card = sel.closest('.cap-card');
  if (!card) return;
  const mt = card.dataset.modelType;
  const prov = sel.value;
  const modelEl = card.querySelector('.cap-model');
  const adapterEl = card.querySelector('.cap-adapter');
  if (adapterEl) {{
    adapterEl.value = prov === 'gemini' ? 'gemini_generate_content' : mt === 'vision' ? 'openai_vision' : 'openai_chat';
  }}
  const opts = (MODELS[mt] || MODELS['text'] || {{}})[prov] || [];
  const prev = modelEl.value;
  modelEl.innerHTML = '';
  opts.forEach(m => {{ const o = new Option(m, m, false, m===prev); modelEl.add(o); }});
}}

// Update search default dropdown when keys change
function refreshSearchDefault() {{
  const active = activeProviders();
  const sel = document.getElementById('search-default-select');
  if (!sel) return;
  Array.from(sel.options).forEach(opt => {{
    if (opt.value === 'auto') return;
    opt.disabled = !active.has(opt.value);
    opt.textContent = opt.textContent.replace(/ \\(немає ключа\\)$/, '');
    if (opt.disabled) opt.textContent += ' (немає ключа)';
  }});
}}

document.querySelectorAll('.prov-key-input').forEach(i => i.addEventListener('input', () => {{ refreshProviderDropdowns(); refreshSearchDefault(); }}));
document.querySelectorAll('.cap-provider').forEach(s => s.addEventListener('change', () => refreshModels(s)));
refreshProviderDropdowns();
refreshSearchDefault();
</script>
</body>
</html>"""


def render_prompts_page(values: dict[str, str], flash: str = "", flash_kind: str = "info") -> str:
    """Render the prompts editing page."""
    defaults = _get_prompt_defaults()
    flash_html = (
        f'<div class="flash flash-{html.escape(flash_kind)}">{html.escape(flash)}</div>'
        if flash else ""
    )

    # Resolve effective model per capability (same logic as main page)
    cap_map = {c.slug: c for c in CAPABILITIES}

    cards = ""
    for pd in PROMPT_DEFS:
        cap = cap_map.get(pd.capability)
        if cap:
            eff_model = _effective_model(cap, values)
            eff_provider = _effective_provider(cap, values)
        else:
            eff_model = "—"
            eff_provider = "—"

        # Current value: env override wins, otherwise show code default
        env_override = values.get(pd.env_key, "").strip()
        code_default = defaults.get(pd.slug, "") if pd.slug != "persona" else ""
        # What to show in textarea: env override if set, otherwise code default
        text_value = env_override if env_override else code_default
        is_override = bool(env_override)

        override_badge = '<span class="badge badge-override">Змінено</span>' if is_override else '<span class="badge badge-default">Дефолт</span>'

        # Count lines for textarea height
        line_count = max(4, min(20, text_value.count('\n') + 2))

        cards += f'''<div class="prompt-card">
          <div class="prompt-top">
            <h3>{html.escape(pd.title)}</h3>
            <span class="badge badge-model" title="Провайдер: {html.escape(eff_provider)}">{html.escape(eff_model)}</span>
            {override_badge}
          </div>
          <p class="prompt-desc">{html.escape(pd.description)}</p>
          <div class="prompt-stage">Етап: <strong>{html.escape(pd.stage)}</strong></div>
          <textarea class="prompt-text" name="{html.escape(pd.env_key)}" rows="{line_count}">{html.escape(text_value)}</textarea>
          <p class="prompt-hint">Env: <code>{html.escape(pd.env_key)}</code> &middot; Capability: <code>{html.escape(pd.capability)}</code></p>
        </div>'''

    return f"""<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smartest — Промпти</title>
<style>
:root {{
  --bg: #f3ead9; --paper: rgba(255,248,236,0.88); --ink: #1f1d19;
  --muted: #655d4d; --line: rgba(59,45,30,0.14); --accent: #bf4b2c;
  --accent2: #204d46; --ok: #2c6b44; --warn: #935a14;
  --sh: 0 24px 60px rgba(52,36,18,0.12);
}}
*{{ box-sizing:border-box; }}
body{{ margin:0; min-height:100vh; font-family:"IBM Plex Sans","Segoe UI",sans-serif; color:var(--ink);
  background: radial-gradient(circle at top left,rgba(191,75,44,.22),transparent 32%),
    radial-gradient(circle at bottom right,rgba(32,77,70,.18),transparent 28%),
    linear-gradient(135deg,#efe1c4 0%,#f7f0e3 42%,#e8dcc5 100%);
}}
.sh{{ max-width:1480px; margin:0 auto; padding:28px 18px 48px; }}

.hero-card{{
  background:var(--paper); backdrop-filter:blur(12px);
  border:1px solid var(--line); border-radius:24px; box-shadow:var(--sh);
  padding:28px; margin-bottom:24px;
}}
.hero-card h1{{ margin:0 0 10px; font-size:clamp(1.6rem,3vw,2.4rem); line-height:.95; letter-spacing:-.04em; }}
.hero-card p{{ margin:0; color:var(--muted); max-width:62ch; }}
.nav-link{{ color:var(--accent2); font-weight:700; text-decoration:none; }}
.nav-link:hover{{ text-decoration:underline; }}

.flash{{ margin-bottom:20px; padding:14px 16px; border-radius:16px; font-weight:600; }}
.flash-info{{ background:rgba(32,77,70,.12); color:var(--accent2); border:1px solid rgba(32,77,70,.18); }}
.flash-error{{ background:rgba(191,75,44,.12); color:#8b2e14; border:1px solid rgba(191,75,44,.18); }}

.toolbar{{ display:flex; gap:12px; flex-wrap:wrap; justify-content:space-between; align-items:center; margin-bottom:18px; }}
.btn{{ border:0; border-radius:999px; padding:14px 20px; font:inherit; font-weight:700; cursor:pointer; transition:transform .16s; }}
.btn:hover{{ transform:translateY(-1px); }}
.btn-main{{ color:#fff7ef; background:linear-gradient(135deg,var(--accent),#d96c44); }}
.btn-sec{{ color:var(--ink); background:rgba(255,255,255,.7); border:1px solid var(--line); }}

.prompt-grid{{ display:grid; gap:20px; grid-template-columns:1fr; }}
.prompt-card{{
  background:var(--paper); backdrop-filter:blur(12px);
  border:1px solid var(--line); border-radius:24px; box-shadow:var(--sh);
  padding:22px; animation:rise .35s ease both;
}}
.prompt-top{{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:6px; }}
.prompt-top h3{{ margin:0; font-size:1.05rem; }}
.badge{{
  display:inline-block; padding:3px 10px; border-radius:999px;
  font-size:.76rem; font-weight:600;
}}
.badge-model{{ background:rgba(32,77,70,.12); color:var(--accent2); }}
.badge-override{{ background:rgba(191,75,44,.12); color:#8b2e14; }}
.badge-default{{ background:rgba(59,45,30,.08); color:var(--muted); }}
.prompt-desc{{ margin:0 0 6px; color:var(--muted); font-size:.92rem; line-height:1.45; }}
.prompt-stage{{ margin:0 0 10px; font-size:.88rem; color:var(--accent2); }}
.prompt-text{{
  width:100%; border:1px solid rgba(59,45,30,.18); border-radius:14px;
  background:rgba(255,255,255,.82); padding:12px 14px; font:inherit; font-size:.88rem;
  color:var(--ink); resize:vertical; min-height:80px; line-height:1.5;
}}
.prompt-text::placeholder{{ color:#baa; font-style:italic; }}
.prompt-hint{{ margin:6px 0 0; color:var(--muted); font-size:.78rem; }}
.prompt-hint code{{ background:rgba(0,0,0,.06); padding:2px 5px; border-radius:6px; font-size:.78rem; }}

.section-label{{
  margin:28px 0 14px; padding:0; font-size:1.1rem; font-weight:700;
  color:var(--accent2); letter-spacing:.02em;
}}

@keyframes rise{{ from{{ opacity:0; transform:translateY(8px); }} to{{ opacity:1; transform:translateY(0); }} }}
@media(max-width:620px){{ .sh{{ padding:18px 14px 34px; }} }}
</style>
</head>
<body>
<div class="sh">
  <div class="hero-card">
    <h1>Промпти</h1>
    <p>Системні промпти для кожного етапу. Модель підтягується з <a class="nav-link" href="/">головної сторінки</a>.
    Порожнє поле = використовується вбудований промпт за замовчуванням.</p>
  </div>
  {flash_html}
  <form method="post" action="/save-prompts">
    <div class="toolbar">
      <button class="btn btn-main" type="submit">Зберегти промпти</button>
      <a class="nav-link" href="/">&larr; Назад до конфігурації</a>
    </div>

    <div class="prompt-grid">
      {cards}
    </div>
  </form>
</div>
</body>
</html>"""


def _read_journal_log(service: str, lines: int = 500) -> str:
    """Read last N lines from systemd journal for a service."""
    try:
        proc = subprocess.run(
            ["journalctl", "-u", service, "--no-pager", "-n", str(lines), "--output=short-iso"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.stdout or proc.stderr or "(порожньо)"
    except FileNotFoundError:
        return "(journalctl не знайдено — логи доступні тільки на сервері)"
    except Exception as exc:
        return f"(помилка: {exc})"


def render_logs_page(values: dict[str, str], service: str = "", lines: int = 500) -> str:
    """Render the logs page with journalctl output."""
    if not service or service not in (MANAGED_BOT_SERVICE, SELF_SERVICE_NAME):
        service = MANAGED_BOT_SERVICE

    log_text = _read_journal_log(service, lines)
    service_label = "Бот" if service == MANAGED_BOT_SERVICE else "Адмін"

    bot_sel = " selected" if service == MANAGED_BOT_SERVICE else ""
    admin_sel = " selected" if service == SELF_SERVICE_NAME else ""

    lines_opts = ""
    for n in [100, 200, 500, 1000, 2000, 5000]:
        sel = " selected" if n == lines else ""
        lines_opts += f'<option value="{n}"{sel}>{n}</option>'

    return f"""<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smartest — Логи ({html.escape(service_label)})</title>
<style>
:root {{
  --bg: #1a1a1a; --paper: #1e1e1e; --ink: #d4d4d4;
  --muted: #888; --line: rgba(255,255,255,0.08); --accent: #bf4b2c;
  --accent2: #4ec9b0; --ok: #4ec9b0; --warn: #d7ba7d;
}}
*{{ box-sizing:border-box; }}
body{{ margin:0; min-height:100vh; font-family:"JetBrains Mono","Fira Code","Consolas",monospace; color:var(--ink);
  background:var(--bg); font-size:13px; }}
.sh{{ display:flex; flex-direction:column; height:100vh; }}

.toolbar{{
  display:flex; gap:12px; align-items:center; flex-wrap:wrap;
  padding:12px 18px; background:var(--paper); border-bottom:1px solid var(--line);
  flex-shrink:0;
}}
.toolbar-title{{ font-weight:700; font-size:1.1rem; color:var(--accent2); margin-right:auto; }}
.nav-link{{ color:var(--accent2); font-weight:600; text-decoration:none; font-size:.9rem; }}
.nav-link:hover{{ text-decoration:underline; }}

select,button{{
  font-family:inherit; font-size:.85rem; padding:6px 12px;
  border:1px solid var(--line); border-radius:8px;
  background:var(--bg); color:var(--ink); cursor:pointer;
}}
button{{ font-weight:700; }}
button:hover{{ background:#333; }}

.log-wrap{{
  flex:1; overflow:auto; padding:12px 18px;
}}
.log-pre{{
  margin:0; white-space:pre-wrap; word-break:break-all; line-height:1.55;
  color:#ccc; font-size:12.5px;
}}
.log-pre .ts{{ color:#6a9955; }}
.log-pre .lvl-err{{ color:#f44747; font-weight:700; }}
.log-pre .lvl-warn{{ color:#d7ba7d; }}
.log-pre .lvl-info{{ color:#4ec9b0; }}

.status-bar{{
  display:flex; gap:16px; align-items:center; padding:8px 18px;
  background:var(--paper); border-top:1px solid var(--line);
  font-size:.82rem; color:var(--muted); flex-shrink:0;
}}
</style>
</head>
<body>
<div class="sh">
  <div class="toolbar">
    <span class="toolbar-title">Логи: {html.escape(service_label)}</span>
    <label>Сервіс:
      <select id="svc-select">
        <option value="{html.escape(MANAGED_BOT_SERVICE)}"{bot_sel}>Бот</option>
        <option value="{html.escape(SELF_SERVICE_NAME)}"{admin_sel}>Адмін</option>
      </select>
    </label>
    <label>Рядків:
      <select id="lines-select">
        {lines_opts}
      </select>
    </label>
    <button onclick="reload()">Оновити</button>
    <button onclick="scrollEnd()">&#8595; Кінець</button>
    <a class="nav-link" href="/">&larr; Конфігурація</a>
    <a class="nav-link" href="/prompts">Промпти</a>
  </div>
  <div class="log-wrap" id="log-wrap">
    <pre class="log-pre" id="log-pre">{html.escape(log_text)}</pre>
  </div>
  <div class="status-bar">
    <span>Сервіс: {html.escape(service)}</span>
    <span>Рядків: {log_text.count(chr(10))}</span>
    <span id="auto-label"></span>
  </div>
</div>
<script>
function reload() {{
  const svc = document.getElementById('svc-select').value;
  const n = document.getElementById('lines-select').value;
  window.location.href = '/logs?service=' + encodeURIComponent(svc) + '&lines=' + n;
}}
function scrollEnd() {{
  const el = document.getElementById('log-wrap');
  el.scrollTop = el.scrollHeight;
}}
document.getElementById('svc-select').addEventListener('change', reload);
document.getElementById('lines-select').addEventListener('change', reload);
// Auto-scroll to bottom on load
scrollEnd();

// Auto-refresh every 10s
let autoTimer = setInterval(() => {{
  fetch('/logs-text?service=' + encodeURIComponent(document.getElementById('svc-select').value) + '&lines=' + document.getElementById('lines-select').value)
    .then(r => r.text())
    .then(t => {{
      const pre = document.getElementById('log-pre');
      const wrap = document.getElementById('log-wrap');
      const wasBottom = (wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight) < 60;
      pre.textContent = t;
      if (wasBottom) scrollEnd();
    }}).catch(() => {{}});
}}, 10000);
document.getElementById('auto-label').textContent = 'Авто-оновлення: 10с';
</script>
</body>
</html>"""


def render_login(message: str = "") -> str:
    flash = f'<div class="login-flash">{html.escape(message)}</div>' if message else ""
    return f"""<!doctype html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smartest Login</title>
<style>
:root {{ --bg:#efe1c4; --paper:rgba(255,248,236,.9); --ink:#1f1d19; --muted:#6a624f; --accent:#bf4b2c; --line:rgba(59,45,30,.14); --sh:0 30px 80px rgba(44,28,10,.16); }}
*{{ box-sizing:border-box; }}
body{{ margin:0; min-height:100vh; display:grid; place-items:center; font-family:"IBM Plex Sans","Segoe UI",sans-serif; color:var(--ink);
  background: radial-gradient(circle at top left,rgba(191,75,44,.2),transparent 30%), radial-gradient(circle at bottom right,rgba(32,77,70,.16),transparent 26%), linear-gradient(145deg,#f4e8cf 0%,#fbf6ec 55%,#eadfc9 100%); padding:18px; }}
.card{{ width:min(100%,430px); background:var(--paper); border:1px solid var(--line); border-radius:28px; box-shadow:var(--sh); padding:28px; }}
h1{{ margin:0 0 12px; font-size:clamp(2rem,5vw,2.8rem); line-height:.94; letter-spacing:-.04em; }}
p{{ margin:0 0 20px; color:var(--muted); line-height:1.55; }}
.field{{ display:block; margin-top:14px; }}
.field span{{ display:block; margin-bottom:8px; font-weight:700; font-size:.92rem; }}
input{{ width:100%; border:1px solid rgba(59,45,30,.18); border-radius:14px; background:rgba(255,255,255,.84); padding:13px 14px; font:inherit; color:var(--ink); }}
button{{ width:100%; margin-top:18px; border:0; border-radius:999px; padding:14px 18px; font:inherit; font-weight:700; color:#fff7ef; background:linear-gradient(135deg,var(--accent),#d96c44); cursor:pointer; }}
.login-flash{{ margin-bottom:16px; padding:12px 14px; border-radius:14px; background:rgba(191,75,44,.12); color:#8b2e14; border:1px solid rgba(191,75,44,.18); font-weight:600; }}
</style>
</head>
<body>
<form class="card" method="post" action="/login">
  <h1>Smartest<br>Control</h1>
  <p>Увійди в панель керування.</p>
  {flash}
  <label class="field"><span>Логін</span><input name="username" autocomplete="username" required></label>
  <label class="field"><span>Пароль</span><input type="password" name="password" autocomplete="current-password" required></label>
  <button type="submit">Увійти</button>
</form>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class SmartestAdminHandler(BaseHTTPRequestHandler):
    server_version = "SmartestAdmin/1.0"

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s | %s", self.address_string(), fmt % args)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_text("ok", head_only=True); return
        if parsed.path == "/login":
            self._send_html(render_login(self._query_param(parsed.query, "message")), head_only=True); return
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND); return
        if not self._current_session():
            self._redirect("/login"); return
        values = read_current_config()
        self._send_html(render_dashboard(values, flash=self._query_param(parsed.query, "flash"), flash_kind=self._query_param(parsed.query, "kind") or "info"), head_only=True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_text("ok"); return
        if parsed.path == "/login":
            self._send_html(render_login(self._query_param(parsed.query, "message"))); return
        if parsed.path == "/prompts":
            if not self._current_session():
                self._redirect("/login"); return
            values = read_current_config()
            self._send_html(render_prompts_page(values, flash=self._query_param(parsed.query, "flash"), flash_kind=self._query_param(parsed.query, "kind") or "info")); return
        if parsed.path == "/logs":
            if not self._current_session():
                self._redirect("/login"); return
            values = read_current_config()
            svc = self._query_param(parsed.query, "service") or MANAGED_BOT_SERVICE
            lines = min(5000, max(50, int(self._query_param(parsed.query, "lines") or "500")))
            self._send_html(render_logs_page(values, service=svc, lines=lines)); return
        if parsed.path == "/logs-text":
            if not self._current_session():
                self._send_text("unauthorized", status=HTTPStatus.UNAUTHORIZED); return
            svc = self._query_param(parsed.query, "service") or MANAGED_BOT_SERVICE
            if svc not in (MANAGED_BOT_SERVICE, SELF_SERVICE_NAME):
                svc = MANAGED_BOT_SERVICE
            lines = min(5000, max(50, int(self._query_param(parsed.query, "lines") or "500")))
            self._send_text(_read_journal_log(svc, lines)); return
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND); return
        if not self._current_session():
            self._redirect("/login"); return
        values = read_current_config()
        self._send_html(render_dashboard(values, flash=self._query_param(parsed.query, "flash"), flash_kind=self._query_param(parsed.query, "kind") or "info"))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self._handle_login(); return
        if parsed.path == "/logout":
            self._clear_session(); return
        if parsed.path == "/save":
            if not self._current_session():
                self._redirect("/login?" + urlencode({"message": "Потрібен повторний вхід."})); return
            self._handle_save(); return
        if parsed.path == "/clear-memory":
            if not self._current_session():
                self._redirect("/login?" + urlencode({"message": "Потрібен повторний вхід."})); return
            self._handle_clear_memory(); return
        if parsed.path == "/save-prompts":
            if not self._current_session():
                self._redirect("/login?" + urlencode({"message": "Потрібен повторний вхід."})); return
            self._handle_save_prompts(); return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _body_params(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", "replace")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: vals[-1] if vals else "" for key, vals in parsed.items()}

    def _query_param(self, query: str, key: str) -> str:
        parsed = parse_qs(query, keep_blank_values=True)
        values = parsed.get(key)
        return values[-1] if values else ""

    def _current_session(self) -> dict | None:
        cookie_header = self.headers.get("Cookie", "")
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get(COOKIE_NAME)
        if not morsel:
            return None
        values = read_current_config()
        secret = values.get(_session_secret_key()) or os.getenv(_session_secret_key()) or ""
        if not secret:
            return None
        return parse_session_token(morsel.value, secret)

    def _set_session(self, username: str) -> None:
        values = read_current_config()
        secret = ensure_session_secret(values)
        token = session_token(username, secret)
        self.send_header("Set-Cookie", f"{COOKIE_NAME}={token}; Max-Age={SESSION_MAX_AGE}; Path=/; HttpOnly; SameSite=Lax")

    def _clear_session(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")
        self.send_header("Location", "/login?" + urlencode({"message": "Сесію завершено."}))
        self.end_headers()

    def _handle_login(self) -> None:
        params = self._body_params()
        values = read_current_config()
        username = params.get("username", "").strip()
        password = params.get("password", "")
        if username != admin_username(values) or password != admin_password(values):
            self._send_html(render_login("Невірний логін або пароль."), status=HTTPStatus.UNAUTHORIZED)
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self._set_session(username)
        self.send_header("Location", "/?" + urlencode({"flash": "Вхід успішний.", "kind": "info"}))
        self.end_headers()

    def _handle_save(self) -> None:
        params = self._body_params()
        updates: dict[str, str] = {}

        # Provider keys
        for p in PROVIDERS:
            updates[p.key_env] = params.get(p.key_env, "").strip()
            # Write base URL from constants (not user-editable)
            if p.slug in BASE_URLS and BASE_URLS[p.slug]:
                url_key = f"PROVIDER_{p.slug.upper()}_BASE_URL"
                updates[url_key] = BASE_URLS[p.slug]

        # Default search provider
        updates["SEARCH_PROVIDER"] = params.get("SEARCH_PROVIDER", "auto").strip() or "auto"

        # Gemini thinking budget (keep existing value)
        existing = read_current_config()
        gb = existing.get("PROVIDER_GEMINI_THINKING_BUDGET", "0")
        updates["PROVIDER_GEMINI_THINKING_BUDGET"] = gb

        # Dashboard env fields
        for f in [*VOICE_FIELDS, *TUNING_FIELDS, *GLOBAL_FIELDS]:
            updates[f.key] = params.get(f.key, "").strip()

        # Access
        updates["SMARTEST_ADMIN_USERNAME"] = params.get("SMARTEST_ADMIN_USERNAME", "").strip()
        updates["SMARTEST_ADMIN_PASSWORD"] = params.get("SMARTEST_ADMIN_PASSWORD", "").strip()

        # Capabilities
        for cap in CAPABILITIES:
            prov = params.get(capability_field_key(cap.slug, "PROVIDER"), "").strip() or cap.default_provider
            model = params.get(capability_field_key(cap.slug, "MODEL"), "").strip() or cap.default_model
            adapter = _auto_adapter(prov, cap.model_type)
            custom_key = params.get(capability_field_key(cap.slug, "API_KEY"), "").strip()

            updates[capability_field_key(cap.slug, "PROVIDER")] = prov
            updates[capability_field_key(cap.slug, "MODEL")] = model
            updates[capability_field_key(cap.slug, "ADAPTER")] = adapter
            if custom_key:
                updates[capability_field_key(cap.slug, "API_KEY")] = custom_key

        # Preserve credentials
        values_before = read_current_config()
        if not updates.get(_admin_username_key()):
            updates[_admin_username_key()] = values_before.get(_admin_username_key()) or "admin"
        if not updates.get(_admin_password_key()):
            updates[_admin_password_key()] = values_before.get(_admin_password_key()) or "admin"
        if _session_secret_key() not in values_before:
            updates[_session_secret_key()] = ensure_session_secret(values_before)

        write_env_updates(ENV_PATH, updates)

        restarted = False
        if params.get("restart_bot") == "1":
            ok, _ = restart_service(MANAGED_BOT_SERVICE)
            restarted = ok

        flash = "Конфіг збережено."
        if params.get("restart_bot") == "1":
            flash += " Бот перезапущено." if restarted else " Рестарт не підтверджено."

        self._redirect("/?" + urlencode({
            "flash": flash,
            "kind": "info" if restarted or params.get("restart_bot") != "1" else "error",
        }))

    def _handle_save_prompts(self) -> None:
        params = self._body_params()
        updates: dict[str, str] = {}

        for pd in PROMPT_DEFS:
            val = params.get(pd.env_key, "").strip()
            updates[pd.env_key] = val

        write_env_updates(ENV_PATH, updates)

        self._redirect("/prompts?" + urlencode({
            "flash": "Промпти збережено. Перезапустіть бота на головній сторінці для застосування.",
            "kind": "info",
        }))

    def _handle_clear_memory(self) -> None:
        ok, _ = clear_bot_memory()
        self._redirect("/?" + urlencode({
            "flash": (
                "Пам'ять бота очищено для всіх чатів."
                if ok
                else "Не вдалося очистити пам'ять бота."
            ),
            "kind": "info" if ok else "error",
        }))

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _send_html(self, content: str, status: HTTPStatus = HTTPStatus.OK, *, head_only: bool = False) -> None:
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if not head_only:
            self.wfile.write(encoded)

    def _send_text(self, content: str, status: HTTPStatus = HTTPStatus.OK, *, head_only: bool = False) -> None:
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if not head_only:
            self.wfile.write(encoded)


def main() -> None:
    logger.info("admin.boot env_path=%s host=%s port=%s", ENV_PATH, HOST, PORT)
    values = read_current_config()
    if _admin_username_key() not in values or _admin_password_key() not in values:
        write_env_updates(ENV_PATH, {
            _admin_username_key(): values.get(_admin_username_key()) or "admin",
            _admin_password_key(): values.get(_admin_password_key()) or "admin",
        })
    ensure_session_secret(read_current_config())
    server = ThreadingHTTPServer((HOST, PORT), SmartestAdminHandler)
    logger.info("admin.ready host=%s port=%s", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("admin.stop_signal")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
