from __future__ import annotations

import base64
import asyncio
import cgi
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
from decimal import Decimal
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlparse

from core.env import can_reason, telegram_bot_token
from core.logging_setup import log_file_for, setup_logging
from core.model_preferences import MODEL_GROUPS
from core.podcast import (
    podcast_healthcheck,
    podcast_runtime_config,
    store_service_account_secret,
)
from billing.crypto import decrypt_key
from billing.keypool import register_key as register_provider_key
from db.admin_repository import (
    credit_account_admin,
    get_chats_summary,
    get_provider_keys_summary,
    get_topups_summary,
    get_user_admin_detail,
    get_transactions_summary,
    list_chats_with_stats,
    list_provider_keys_with_stats,
    list_topups_with_stats,
    list_transactions_with_stats,
    normalize_key_sort,
    normalize_chat_sort,
    normalize_topup_sort,
    list_users_with_stats,
    normalize_transaction_sort,
    normalize_user_sort,
)
from db.keypool_repository import get_provider_key, set_key_status
from db.portal_repository import (
    create_portal_topup_request,
    ensure_portal_identity,
    get_portal_dashboard,
    get_portal_history,
    get_portal_settings,
    get_portal_topups,
    get_portal_turn_detail,
    update_portal_settings,
)
from memory import memory_manager

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
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
USER_COOKIE_NAME = "_smartest_user"
USER_OAUTH_COOKIE_NAME = "_smartest_tg_oauth"
ADMIN_PASSWORD_LOGIN_PATH = os.getenv("SMARTEST_ADMIN_PASSWORD_LOGIN_PATH", "/403").strip() or "/403"
if not ADMIN_PASSWORD_LOGIN_PATH.startswith("/"):
    ADMIN_PASSWORD_LOGIN_PATH = "/" + ADMIN_PASSWORD_LOGIN_PATH
SESSION_MAX_AGE = 60 * 60 * 24 * 30
USER_OAUTH_MAX_AGE = 60 * 10
JWKS_CACHE_TTL = 60 * 60
HOST = os.getenv("SMARTEST_ADMIN_HOST", "127.0.0.1")
PORT = int(os.getenv("SMARTEST_ADMIN_PORT", "8787"))
MANAGED_BOT_SERVICE = os.getenv("SMARTEST_MANAGED_SERVICE", "smartest-bot.service")
SELF_SERVICE_NAME = os.getenv("SMARTEST_ADMIN_SERVICE_NAME", "smartest-admin.service")
BOT_TRACE_LOG = log_file_for("smartest-bot")
ADMIN_TRACE_LOG = log_file_for("smartest-admin")
_JWKS_CACHE: dict[str, object] = {"fetched_at": 0.0, "keys": None}

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
PROVIDER_LABELS = {p.slug: p.label for p in PROVIDERS}

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
        "stt_voice", "Голос / STT",
        "Розпізнавання мовлення з аудіо.",
        "media", "Тільки OpenAI whisper/transcribe",
        "stt", "openai", "gpt-4o-transcribe",
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
        "search_gate", "Фільтр пошуку (Search Gate)",
        "Друга лінія перевірки. Коли planner вирішив шукати, gate вирішує чи справді потрібен інтернет, чи модель знає відповідь.",
        "Крок 1b: Валідація пошуку",
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

def _user_session_secret_key() -> str:
    return "SMARTEST_USER_SESSION_SECRET"

def _admin_tg_user_ids_key() -> str:
    return "ADMIN_TG_USER_IDS"

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

def _ensure_secret(values: dict[str, str], env_key: str, *, fallback_key: str = "") -> str:
    secret = values.get(env_key) or os.getenv(env_key) or ""
    if secret:
        return secret
    if fallback_key:
        fallback = values.get(fallback_key) or os.getenv(fallback_key) or ""
        if fallback:
            write_env_updates(ENV_PATH, {env_key: fallback})
            return fallback
    secret = secrets.token_urlsafe(32)
    write_env_updates(ENV_PATH, {env_key: secret})
    return secret


def ensure_session_secret(values: dict[str, str]) -> str:
    return _ensure_secret(values, _session_secret_key())


def ensure_user_session_secret(values: dict[str, str]) -> str:
    return _ensure_secret(values, _user_session_secret_key(), fallback_key=_session_secret_key())

def admin_username(values: dict[str, str]) -> str:
    return values.get(_admin_username_key()) or os.getenv(_admin_username_key()) or "admin"

def admin_password(values: dict[str, str]) -> str:
    return values.get(_admin_password_key()) or os.getenv(_admin_password_key()) or "admin"


def _sign_session_payload(payload: dict, secret: str) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{encoded}.{digest}"


def session_token(username: str, secret: str) -> str:
    return _sign_session_payload({"u": username, "exp": int(time.time()) + SESSION_MAX_AGE}, secret)

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


def user_session_token(
    *,
    user_id: int,
    tg_username: str = "",
    display_name: str = "",
    is_admin: bool = False,
    secret: str,
) -> str:
    return _sign_session_payload(
        {
            "user_id": int(user_id),
            "username": tg_username,
            "name": display_name,
            "is_admin": bool(is_admin),
            "exp": int(time.time()) + SESSION_MAX_AGE,
        },
        secret,
    )


def admin_tg_user_ids(values: dict[str, str]) -> set[int]:
    raw = values.get(_admin_tg_user_ids_key()) or os.getenv(_admin_tg_user_ids_key()) or ""
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            continue
    return result


def telegram_login_client_id(values: dict[str, str]) -> str:
    raw = (values.get("TELEGRAM_LOGIN_CLIENT_ID") or os.getenv("TELEGRAM_LOGIN_CLIENT_ID") or "").strip()
    if raw:
        return raw
    token = values.get("TG_BOT_TOKEN") or values.get("MYAPI_BOT_TOKEN") or telegram_bot_token()
    candidate = (token or "").split(":", 1)[0].strip()
    return candidate if candidate.isdigit() else ""


def _jwks_cache_get() -> object | None:
    fetched_at = float(_JWKS_CACHE.get("fetched_at") or 0.0)
    if fetched_at and (time.time() - fetched_at) < JWKS_CACHE_TTL:
        return _JWKS_CACHE.get("keys")
    return None


def _jwks_cache_put(keys: object) -> None:
    _JWKS_CACHE["fetched_at"] = time.time()
    _JWKS_CACHE["keys"] = keys


def verify_telegram_token(id_token: str, bot_id: str, *, expected_nonce: str | None = None) -> dict:
    try:
        import httpx
        from jose import jwt
    except Exception as exc:
        raise RuntimeError("Telegram Login backend requires python-jose[cryptography].") from exc
    jwks = _jwks_cache_get()
    if jwks is None:
        response = httpx.get("https://oauth.telegram.org/.well-known/jwks.json", timeout=10.0)
        response.raise_for_status()
        jwks = response.json()
        _jwks_cache_put(jwks)
    claims = jwt.decode(
        id_token,
        jwks,
        algorithms=["RS256"],
        audience=str(bot_id),
        issuer="https://oauth.telegram.org",
    )
    if expected_nonce is not None:
        token_nonce = str(claims.get("nonce") or "")
        if token_nonce != expected_nonce:
            raise RuntimeError("Telegram token nonce mismatch.")
    return claims


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

def read_current_config() -> dict[str, str]:
    return env_map_from_lines(read_env_lines(ENV_PATH))


def _podcast_enabled_from_params(params: dict[str, str]) -> str:
    return "1" if params.get("PODCAST_NOTEBOOKLM_ENABLED") == "1" else ""


def _podcast_status_updates(
    health,
    *,
    enabled: str,
    project_id: str,
    location: str,
    secret_path: str,
) -> dict[str, str]:
    checked_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    return {
        "PODCAST_NOTEBOOKLM_ENABLED": enabled,
        "PODCAST_NOTEBOOKLM_PROJECT_ID": project_id,
        "PODCAST_NOTEBOOKLM_LOCATION": location,
        "PODCAST_NOTEBOOKLM_SECRET_PATH": secret_path,
        "PODCAST_NOTEBOOKLM_CLIENT_EMAIL": health.client_email,
        "PODCAST_NOTEBOOKLM_CLIENT_ID": health.client_id,
        "PODCAST_NOTEBOOKLM_READY": "1" if health.ready else "",
        "PODCAST_NOTEBOOKLM_STATUS": health.status,
        "PODCAST_NOTEBOOKLM_STATUS_MESSAGE": health.message,
        "PODCAST_NOTEBOOKLM_LAST_CHECKED_AT": checked_at,
    }

def capability_field_key(slug: str, suffix: str) -> str:
    return f"CAPABILITY_{slug.upper()}_{suffix}"

# ---------------------------------------------------------------------------
# Resolve effective values (what the bot ACTUALLY uses)
# ---------------------------------------------------------------------------

def _allowed_providers_for(cap: CapabilityDef) -> list[str]:
    return list(MODELS.get(cap.model_type, MODELS.get("text", {})).keys())


def _allowed_models_for(cap: CapabilityDef, provider: str) -> list[str]:
    return list(MODELS.get(cap.model_type, MODELS.get("text", {})).get(provider, []))


def _normalize_provider_for_capability(cap: CapabilityDef, provider: str) -> str:
    requested = (provider or "").strip().lower()
    allowed = _allowed_providers_for(cap)
    if requested in allowed:
        return requested
    if cap.default_provider in allowed:
        return cap.default_provider
    return allowed[0] if allowed else cap.default_provider


def _legacy_capability_model(cap: CapabilityDef, values: dict[str, str]) -> str:
    slug_upper = cap.slug.upper()
    if slug_upper == "PLANNER_REASONING":
        return (
            values.get("OPENAI_PLANNER_MODEL", "").strip()
            or values.get("OPENAI_CHAT_MODEL", "").strip()
            or values.get("OPENAI_GPT_MODEL", "").strip()
        )
    if slug_upper == "VISION_IMAGE":
        return (
            values.get("OPENAI_VISION_MODEL", "").strip()
            or values.get("VISION_MODEL", "").strip()
            or values.get("OPENAI_CHAT_MODEL", "").strip()
            or values.get("OPENAI_GPT_MODEL", "").strip()
        )
    if slug_upper == "MEMORY_SUMMARY":
        return (
            values.get("OPENAI_SUMMARIZER_MODEL", "").strip()
            or values.get("OPENAI_CHAT_MODEL", "").strip()
            or values.get("OPENAI_GPT_MODEL", "").strip()
        )
    return values.get("OPENAI_CHAT_MODEL", "").strip() or values.get("OPENAI_GPT_MODEL", "").strip()


def _normalize_model_for_capability(cap: CapabilityDef, provider: str, model: str, values: dict[str, str]) -> str:
    allowed_models = _allowed_models_for(cap, provider)
    requested = (model or "").strip()
    if requested and requested in allowed_models:
        return requested
    if cap.default_provider == provider and cap.default_model in allowed_models:
        return cap.default_model
    legacy = _legacy_capability_model(cap, values)
    if legacy and legacy in allowed_models:
        return legacy
    return allowed_models[0] if allowed_models else (requested or cap.default_model)


def _normalized_capability_binding(
    cap: CapabilityDef,
    values: dict[str, str],
    *,
    provider: str = "",
    model: str = "",
) -> tuple[str, str, str]:
    resolved_provider = _normalize_provider_for_capability(
        cap,
        provider or values.get(capability_field_key(cap.slug, "PROVIDER"), "").strip() or values.get("DEFAULT_LLM_PROVIDER", "").strip(),
    )
    resolved_model = _normalize_model_for_capability(
        cap,
        resolved_provider,
        model or values.get(capability_field_key(cap.slug, "MODEL"), "").strip(),
        values,
    )
    return resolved_provider, resolved_model, _auto_adapter(resolved_provider, cap.model_type)


def _effective_provider(cap: CapabilityDef, values: dict[str, str]) -> str:
    provider, _, _ = _normalized_capability_binding(cap, values)
    return provider

def _effective_model(cap: CapabilityDef, values: dict[str, str]) -> str:
    _, model, _ = _normalized_capability_binding(cap, values)
    return model


def _effective_reasoning_enabled(cap: CapabilityDef, values: dict[str, str]) -> bool:
    key = capability_field_key(cap.slug, "REASONING_ENABLED")
    return (values.get(key, "").strip() == "1")


def _effective_reasoning_effort(cap: CapabilityDef, values: dict[str, str]) -> str:
    key = capability_field_key(cap.slug, "REASONING_EFFORT")
    raw = (values.get(key, "").strip().lower() or "medium")
    return raw if raw in {"low", "medium", "high"} else "medium"

# ---------------------------------------------------------------------------
# Rendering: dashboard
# ---------------------------------------------------------------------------

FLASH_KINDS = {"info", "ok", "warn", "error"}


def _normalize_flash_kind(kind: str) -> str:
    candidate = (kind or "info").strip().lower()
    if candidate == "success":
        return "ok"
    if candidate == "danger":
        return "error"
    return candidate if candidate in FLASH_KINDS else "info"


def _flash_block(flash: str, flash_kind: str) -> str:
    if not flash:
        return ""
    kind = _normalize_flash_kind(flash_kind)
    return f'<div class="flash flash-{kind}">{html.escape(flash)}</div>'


def _shared_head(title: str, *, extra_head: str = "") -> str:
    return f"""<!doctype html>
<html lang=\"uk\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>{html.escape(title)}</title>
<link rel=\"stylesheet\" href=\"/static/admin.css\">
{extra_head}
</head>"""


def render_dashboard(values: dict[str, str], flash: str = "", flash_kind: str = "info") -> str:
    bot_status = service_status(MANAGED_BOT_SERVICE)
    admin_status = service_status(SELF_SERVICE_NAME)
    env_mtime = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ENV_PATH.stat().st_mtime))
        if ENV_PATH.exists() else "-"
    )
    podcast_cfg = podcast_runtime_config(values)
    podcast_enabled_checked = " checked" if podcast_cfg.enabled else ""
    podcast_status_class = "st-ok" if podcast_cfg.ready else "st-warn"
    podcast_status_label = "Ready" if podcast_cfg.ready else "Inactive"
    podcast_checked_at = html.escape(
        values.get("PODCAST_NOTEBOOKLM_LAST_CHECKED_AT", "").strip() or "—"
    )
    podcast_secret_name = html.escape(
        Path(podcast_cfg.secret_path).name if podcast_cfg.secret_path else "—"
    )
    podcast_client_email = html.escape(podcast_cfg.client_email or "—")
    podcast_message = html.escape(podcast_cfg.status_message or "Сервіс подкастів ще не налаштований.")
    flash_html = _flash_block(flash, flash_kind)

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

    podcast_panel = f'''<section class="panel">
      <h2>NotebookLM Podcast</h2>
      <p class="panel-desc">Окремий downstream-сервіс для генерації MP3-подкастів. Поки readiness-check не пройдено, цей capability вважається повністю вимкненим і не має права впливати на runtime.</p>
      <div class="acc-grid">
        <label class="acc-label"><input type="checkbox" name="PODCAST_NOTEBOOKLM_ENABLED" value="1"{podcast_enabled_checked}> Увімкнути podcast capability після успішної перевірки</label>
        <label class="acc-label">Project ID<input class="inp" type="text" name="PODCAST_NOTEBOOKLM_PROJECT_ID" value="{html.escape(podcast_cfg.project_id)}" placeholder="notebooklm-492911"></label>
        <label class="acc-label">Location<input class="inp" type="text" name="PODCAST_NOTEBOOKLM_LOCATION" value="{html.escape(podcast_cfg.location or 'global')}" placeholder="global"></label>
      </div>
      <div class="st-grid" style="margin-top:18px;">
        <div class="st-card"><span class="st-lbl">Status</span><div class="st-val {podcast_status_class}">{podcast_status_label}</div></div>
        <div class="st-card"><span class="st-lbl">Перевірка</span><div class="st-val">{podcast_checked_at}</div></div>
        <div class="st-card"><span class="st-lbl">Secret</span><div class="st-val">{podcast_secret_name}</div></div>
        <div class="st-card"><span class="st-lbl">Service account</span><div class="st-val">{podcast_client_email}</div></div>
      </div>
      <p class="acc-help" style="margin-top:14px;">{podcast_message}</p>
      <div class="toolbar" style="margin-top:18px;">
        <div class="toolbar-left">
          <input class="inp" type="file" name="PODCAST_NOTEBOOKLM_SECRET_FILE" accept=".json,application/json">
          <button class="btn btn-sec" type="submit" formaction="/upload-podcast-secret" formenctype="multipart/form-data" formmethod="post">Завантажити JSON і перевірити доступ</button>
          <button class="btn btn-sec" type="submit" formaction="/check-podcast" formmethod="post">Перевірити ще раз</button>
        </div>
      </div>
    </section>'''

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
            reasoning_supported = can_reason(eff_provider, eff_model)
            reasoning_enabled = _effective_reasoning_enabled(cap, values) and reasoning_supported
            reasoning_effort = _effective_reasoning_effort(cap, values)
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
            reasoning_checked = " checked" if reasoning_enabled else ""
            reasoning_disabled = "" if reasoning_supported else " disabled"
            reasoning_display = "" if reasoning_enabled else ' style="display:none"'
            effort_options = ""
            for effort_value, effort_label in (
                ("low", "Low"),
                ("medium", "Medium"),
                ("high", "High"),
            ):
                selected = " selected" if effort_value == reasoning_effort else ""
                effort_options += f'<option value="{effort_value}"{selected}>{effort_label}</option>'

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
              <div class="reasoning-controls">
                <label class="reasoning-toggle"><input type="checkbox" class="reasoning-check" name="{capability_field_key(cap.slug, "REASONING_ENABLED")}" value="1" data-cap="{cap.slug}"{reasoning_checked}{reasoning_disabled}> Reasoning</label>
                <div class="reasoning-effort" data-cap="{cap.slug}"{reasoning_display}>
                  <label class="cap-label">Effort
                    <select class="inp reasoning-effort-select" name="{capability_field_key(cap.slug, "REASONING_EFFORT")}" data-cap="{cap.slug}">
                      {effort_options}
                    </select>
                  </label>
                </div>
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
    adv_fields = ""
    for f in GLOBAL_FIELDS:
        v = html.escape(values.get(f.key, "") or f.placeholder)
        adv_fields += f'<label class="adv-label">{html.escape(f.label)}<input class="inp" type="text" name="{html.escape(f.key)}" value="{v}" placeholder="{html.escape(f.placeholder)}"></label>'

    return f"""{_shared_head("Smartest · Config")}
<body>
<div class="wrap">
  <div class="topbar">
    <div>
      <span class="ctx-badge ctx-badge--admin">Admin · Config</span>
      <h1>Конфігурація</h1>
      <p>API-ключі провайдерів і моделі агентів. Зміни застосовуються після перезапуску бота.</p>
    </div>
    <nav class="nav">
      <a href="/admin/users">Користувачі</a>
      <a href="/admin/transactions">Транзакції</a>
      <a href="/admin/chats">Чати</a>
      <a href="/admin/topups">Поповнення</a>
      <a href="/admin/keys">Ключі</a>
      <a href="/prompts">Промпти</a>
      <a href="/logs">Логи</a>
      <a class="nav-cross" href="/">У портал</a>
      <form class="nav-form" method="post" action="/admin/logout"><button type="submit">Вийти</button></form>
    </nav>
  </div>
  <section class="panel">
    <div class="meta-grid">
      <div class="stat"><span class="lbl">Bot</span><div class="val {"st-ok" if bot_status=="active" else "st-warn"}">{html.escape(bot_status)}</div></div>
      <div class="stat"><span class="lbl">Admin</span><div class="val {"st-ok" if admin_status=="active" else "st-warn"}">{html.escape(admin_status)}</div></div>
      <div class="stat"><span class="lbl">Env</span><div class="val">{html.escape(env_mtime)}</div></div>
      <div class="stat"><span class="lbl">Service</span><div class="val">{html.escape(MANAGED_BOT_SERVICE)}</div></div>
    </div>
  </section>
  {flash_html}
  <form method="post" action="/save">
    <div class="toolbar">
      <div class="toolbar-left">
        <button class="btn btn-primary" type="submit">Зберегти і перезапустити</button>
        <label class="chk"><input type="checkbox" name="restart_bot" value="1" checked> Перезапустити бота</label>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-secondary" type="submit" formaction="/clear-memory" formmethod="post" onclick="return confirm('Очистити всю пам\\'ять бота? Це видалить recent, long-term і core пам\\'ять для всіх чатів.');">Очистити пам'ять</button>
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

    <!-- Agent groups -->
    {groups_html}

    {podcast_panel}

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

<script>window.SmartestModels = {models_json};</script>
<script src="/static/admin.js" defer></script>
</body>
</html>"""


def render_prompts_page(values: dict[str, str], flash: str = "", flash_kind: str = "info") -> str:
    """Render the prompts editing page."""
    defaults = _get_prompt_defaults()
    flash_html = _flash_block(flash, flash_kind)

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

    extra_css = """<style>
.prompt-grid { display: grid; gap: 20px; grid-template-columns: 1fr; }
.prompt-card { background: var(--paper); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 22px; animation: rise .35s ease both; }
.prompt-top { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.prompt-top h3 { margin: 0; font-size: 1.05rem; }
.badge-model { background: rgba(32,77,70,.12); color: var(--accent-deep); }
.badge-override { background: rgba(191,75,44,.12); color: var(--error); }
.badge-default { background: rgba(59,45,30,.08); color: var(--muted); }
.prompt-desc { margin: 0 0 6px; color: var(--muted); font-size: .92rem; line-height: 1.45; }
.prompt-stage { margin: 0 0 10px; font-size: .88rem; color: var(--accent-deep); }
.prompt-text { width: 100%; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); background: rgba(255,255,255,.9); padding: 12px 14px; font: inherit; font-size: .88rem; color: var(--ink); resize: vertical; min-height: 80px; line-height: 1.5; }
.prompt-hint { margin: 6px 0 0; color: var(--muted); font-size: .78rem; }
.prompt-hint code { background: rgba(0,0,0,.06); padding: 2px 5px; border-radius: 6px; font-size: .78rem; }
</style>"""
    return f"""{_shared_head("Smartest · Промпти", extra_head=extra_css)}
<body>
<div class="wrap">
  <div class="topbar">
    <div>
      <span class="ctx-badge ctx-badge--admin">Admin · Prompts</span>
      <h1>Промпти</h1>
      <p>Системні промпти для кожного етапу. Модель підтягується з <a href="/admin/config">конфігурації</a>. Порожнє поле = вбудований дефолт.</p>
    </div>
    <nav class="nav">
      <a href="/admin/config">Конфіг</a>
      <a href="/admin/users">Користувачі</a>
      <a href="/logs">Логи</a>
      <a class="nav-cross" href="/">У портал</a>
      <form class="nav-form" method="post" action="/admin/logout"><button type="submit">Вийти</button></form>
    </nav>
  </div>
  {flash_html}
  <form method="post" action="/save-prompts">
    <div class="toolbar">
      <div class="toolbar-left">
        <button class="btn btn-primary" type="submit">Зберегти промпти</button>
      </div>
    </div>
    <div class="prompt-grid">
      {cards}
    </div>
  </form>
</div>
</body>
</html>"""


def _service_log_file(service: str) -> Path:
    return BOT_TRACE_LOG if service == MANAGED_BOT_SERVICE else ADMIN_TRACE_LOG


def _tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return f"(trace log не знайдено: {path})"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"(помилка читання trace log: {exc})"
    if not text.strip():
        return "(trace log порожній)"
    rows = text.splitlines()
    return "\n".join(rows[-lines:]) if rows else "(trace log порожній)"


def _read_journal_log(service: str, lines: int = 500) -> str:
    try:
        proc = subprocess.run(
            ["journalctl", "-u", service, "--no-pager", "-n", str(lines), "--output=short-iso"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.stdout or proc.stderr or "(порожньо)"
    except FileNotFoundError:
        return "(journalctl не знайдено — логи доступні тільки на сервері)"
    except Exception as exc:
        return f"(помилка journalctl: {exc})"


def _filter_log_text(
    log_text: str,
    *,
    contains: str = "",
    trace: str = "",
    chat_id: str = "",
    message_id: str = "",
    capability: str = "",
    level: str = "",
) -> str:
    rows = (log_text or "").splitlines()
    if not rows:
        return log_text or "(порожньо)"

    contains_value = (contains or "").strip().lower()
    trace_value = (trace or "").strip().lower()
    chat_value = (chat_id or "").strip().lower()
    message_value = (message_id or "").strip().lower()
    capability_value = (capability or "").strip().lower()
    level_value = (level or "").strip().upper()

    filtered: list[str] = []
    for row in rows:
        haystack = row.lower()
        if contains_value and contains_value not in haystack:
            continue
        if trace_value and f"trace={trace_value}" not in haystack:
            continue
        if chat_value and f"chat_id={chat_value}" not in haystack:
            continue
        if message_value and f"message_id={message_value}" not in haystack:
            continue
        if capability_value and f"capability={capability_value}" not in haystack:
            continue
        if level_value and f" {level_value} " not in row.upper():
            continue
        filtered.append(row)

    return "\n".join(filtered) if filtered else "(нічого не знайдено за цими фільтрами)"


def _read_log_text(
    service: str,
    *,
    lines: int = 500,
    source: str = "auto",
    contains: str = "",
    trace: str = "",
    chat_id: str = "",
    message_id: str = "",
    capability: str = "",
    level: str = "",
) -> tuple[str, str, str]:
    source_value = (source or "auto").strip().lower()
    if source_value not in {"auto", "trace", "journal"}:
        source_value = "auto"

    trace_path = _service_log_file(service)
    actual_source = source_value
    location = ""

    if source_value == "trace":
        raw = _tail_file(trace_path, lines)
        location = str(trace_path)
    elif source_value == "journal":
        raw = _read_journal_log(service, lines)
        location = f"journalctl -u {service}"
    else:
        if trace_path.exists():
            raw = _tail_file(trace_path, lines)
            actual_source = "trace"
            location = str(trace_path)
        else:
            raw = _read_journal_log(service, lines)
            actual_source = "journal"
            location = f"journalctl -u {service}"

    filtered = _filter_log_text(
        raw,
        contains=contains,
        trace=trace,
        chat_id=chat_id,
        message_id=message_id,
        capability=capability,
        level=level,
    )
    return filtered, actual_source, location


def render_logs_page(
    values: dict[str, str],
    service: str = "",
    lines: int = 500,
    *,
    source: str = "auto",
    contains: str = "",
    trace: str = "",
    chat_id: str = "",
    message_id: str = "",
    capability: str = "",
    level: str = "",
) -> str:
    """Render the logs page with trace-file or journal output and filters."""
    del values
    if not service or service not in (MANAGED_BOT_SERVICE, SELF_SERVICE_NAME):
        service = MANAGED_BOT_SERVICE

    log_text, actual_source, location = _read_log_text(
        service,
        lines=lines,
        source=source,
        contains=contains,
        trace=trace,
        chat_id=chat_id,
        message_id=message_id,
        capability=capability,
        level=level,
    )
    service_label = "Бот" if service == MANAGED_BOT_SERVICE else "Адмін"

    bot_sel = " selected" if service == MANAGED_BOT_SERVICE else ""
    admin_sel = " selected" if service == SELF_SERVICE_NAME else ""
    auto_sel = " selected" if actual_source == "trace" and source == "auto" else ""
    if source == "auto":
        auto_sel = " selected"
    trace_sel = " selected" if source == "trace" else ""
    journal_sel = " selected" if source == "journal" else ""

    lines_opts = ""
    for n in [100, 200, 500, 1000, 2000, 5000]:
        sel = " selected" if n == lines else ""
        lines_opts += f'<option value="{n}"{sel}>{n}</option>'

    level_opts = ""
    for option in ["", "INFO", "WARNING", "ERROR"]:
        label = option or "усі"
        sel = " selected" if (level or "").upper() == option else ""
        level_opts += f'<option value="{html.escape(option)}"{sel}>{html.escape(label)}</option>'

    safe_contains = html.escape(contains or "")
    safe_trace = html.escape(trace or "")
    safe_chat_id = html.escape(chat_id or "")
    safe_message_id = html.escape(message_id or "")
    safe_capability = html.escape(capability or "")
    log_line_count = len((log_text or "").splitlines())

    return f"""{_shared_head(f"Smartest — Логи ({service_label})")}
<body class="logs-body">
<div class="logs-shell">
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
    <label>Джерело:
      <select id="source-select">
        <option value="auto"{auto_sel}>auto</option>
        <option value="trace"{trace_sel}>trace file</option>
        <option value="journal"{journal_sel}>journalctl</option>
      </select>
    </label>
    <button onclick="window.smartestLogsReload()">Оновити</button>
    <button onclick="window.smartestLogsScrollEnd()">&#8595; Кінець</button>
    <a class="nav-link" href="/admin/config">&larr; Конфігурація</a>
    <a class="nav-link" href="/prompts">Промпти</a>
  </div>
  <div class="filters">
    <label>chat_id
      <input id="chatid-input" value="{safe_chat_id}" placeholder="99913">
    </label>
    <label>message_id
      <input id="messageid-input" value="{safe_message_id}" placeholder="252483">
    </label>
    <label>trace
      <input id="trace-input" value="{safe_trace}" placeholder="ptb:99913:8">
    </label>
    <label>capability
      <input id="capability-input" value="{safe_capability}" placeholder="search_synthesis">
    </label>
    <label>рівень
      <select id="level-select">
        {level_opts}
      </select>
    </label>
    <label>містить
      <input id="contains-input" value="{safe_contains}" placeholder="search.retry або error">
    </label>
  </div>
  <div class="log-wrap" id="log-wrap">
    <pre class="log-pre" id="log-pre">{html.escape(log_text)}</pre>
  </div>
  <div class="status-bar">
    <span>Сервіс: {html.escape(service)}</span>
    <span>Джерело: {html.escape(actual_source)}</span>
    <span>Локація: {html.escape(location)}</span>
    <span>Рядків: {log_line_count}</span>
    <span id="auto-label"></span>
  </div>
</div>
<script src="/static/admin.js" defer></script>
</body>
</html>"""


def _fmt_money(value: object, *, places: int = 2) -> str:
    try:
        amount = Decimal(str(value or 0))
    except Exception:
        amount = Decimal("0")
    return f"{amount:.{places}f}"


def _fmt_int(value: object) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", " ")
    except Exception:
        return "0"


def _fmt_dt(value: object, *, with_time: bool = True) -> str:
    if not value:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")
    text = str(value)
    return html.escape(text[:16] if with_time else text[:10])


def _display_user(row: dict) -> str:
    username = (row.get("tg_username") or "").strip()
    name = " ".join(
        part for part in [row.get("first_name"), row.get("last_name")] if part
    ).strip()
    pieces = []
    if username:
        pieces.append(f"@{html.escape(username)}")
    if name:
        pieces.append(html.escape(name))
    if not pieces:
        pieces.append(f"ID {int(row.get('user_id', 0))}")
    return " · ".join(pieces)


def _provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get((provider or "").strip(), provider or "—")


def _mask_provider_key(row: dict) -> str:
    key_hash = str(row.get("key_hash") or "").strip()
    prefix = key_hash[:8] if key_hash else "unknown"
    suffix = "????"
    encrypted = str(row.get("encrypted_key") or "").strip()
    if encrypted:
        try:
            plaintext = decrypt_key(encrypted)
        except Exception:
            plaintext = ""
        if plaintext:
            suffix = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"{prefix}…{suffix}"


def _display_chat(row: dict) -> str:
    title = (row.get("chat_title") or "").strip()
    chat_type = (row.get("tg_chat_type") or "").strip()
    if title and chat_type:
        return f"{html.escape(title)} · {html.escape(chat_type)}"
    if title:
        return html.escape(title)
    if chat_type:
        return html.escape(chat_type)
    return "—"


def _admin_shell(
    *,
    title: str,
    body: str,
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    flash_html = _flash_block(flash, flash_kind)
    return f"""{_shared_head(f"{title} · Smartest Admin")}
<body>
<div class="wrap">
  <div class="topbar">
    <div>
      <span class="ctx-badge ctx-badge--admin">Admin</span>
      <h1>{html.escape(title)}</h1>
      <p>Multitenant admin dashboard.</p>
    </div>
    <nav class="nav">
      <a href="/admin/config">Конфіг</a>
      <a href="/admin/users">Користувачі</a>
      <a href="/admin/transactions">Транзакції</a>
      <a href="/admin/chats">Чати</a>
      <a href="/admin/topups">Поповнення</a>
      <a href="/admin/keys">Ключі</a>
      <a href="/prompts">Промпти</a>
      <a href="/logs">Логи</a>
      <a class="nav-cross" href="/">У портал</a>
      <form class="nav-form" method="post" action="/admin/logout"><button type="submit">Вийти</button></form>
    </nav>
  </div>
  {flash_html}
  {body}
</div>
</body>
</html>"""


def render_admin_users_page(
    rows: list[dict],
    *,
    sort: str,
    direction: str,
    query: str = "",
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    total_balance = sum(Decimal(str(row.get("balance_uah") or 0)) for row in rows)
    total_spent = sum(Decimal(str(row.get("total_spent_uah") or 0)) for row in rows)
    total_turns = sum(int(row.get("turns_total") or 0) for row in rows)

    def sort_href(column: str) -> str:
        next_dir = "asc" if sort != column or direction == "desc" else "desc"
        params = {"sort": column, "dir": next_dir}
        if query:
            params["q"] = query
        return "/admin/users?" + urlencode(params)

    metrics = f"""
    <section class="panel">
      <div class="meta-grid">
        <div class="stat"><span class="lbl">Користувачів</span><div class="val">{_fmt_int(len(rows))}</div></div>
        <div class="stat"><span class="lbl">Сумарний баланс</span><div class="val">{_fmt_money(total_balance)} ₴</div></div>
        <div class="stat"><span class="lbl">Витрачено всього</span><div class="val">{_fmt_money(total_spent)} ₴</div></div>
        <div class="stat"><span class="lbl">Turns всього</span><div class="val">{_fmt_int(total_turns)}</div></div>
      </div>
    </section>
    """

    rows_html = ""
    for row in rows:
        user_id = int(row["user_id"])
        rows_html += f"""
        <tr>
          <td class="mono">{user_id}</td>
          <td>{html.escape(row.get("tg_username") or "—")}</td>
          <td>{html.escape(row.get("first_name") or "—")}</td>
          <td>{_fmt_dt(row.get("first_seen_at"))}</td>
          <td>{_fmt_dt(row.get("last_seen_at"))}</td>
          <td>{_fmt_money(row.get("balance_uah"))}</td>
          <td>{_fmt_money(row.get("total_spent_uah"))}</td>
          <td>{_fmt_money(row.get("total_topup_uah"))}</td>
          <td>{_fmt_int(row.get("turns_total"))}</td>
          <td>{_fmt_int(row.get("turns_today"))}</td>
          <td>{_fmt_int(row.get("turns_7d"))}</td>
          <td>{_fmt_int(row.get("tokens_in"))}</td>
          <td>{_fmt_int(row.get("tokens_out"))}</td>
          <td>{html.escape(row.get("favorite_model") or "—")}</td>
          <td><a class="btn btn-sec" href="/admin/users/{user_id}">Деталі</a></td>
        </tr>
        """
    if not rows_html:
        rows_html = '<tr><td colspan="15" class="muted">Нічого не знайдено.</td></tr>'

    body = f"""
    {metrics}
    <section class="panel">
      <h2>Користувачі</h2>
      <p class="panel-desc">Список акаунтів зі зведеною статистикою по витратах і активності.</p>
      <form class="filters" method="get" action="/admin/users">
        <input type="hidden" name="sort" value="{html.escape(sort)}">
        <input type="hidden" name="dir" value="{html.escape(direction)}">
        <label class="field">
          <span>Пошук</span>
          <input type="text" name="q" value="{html.escape(query)}" placeholder="@username, ім'я або user id">
        </label>
        <button class="btn btn-main" type="submit">Застосувати</button>
      </form>
    </section>
    <section class="panel">
      <table class="data-table">
        <thead>
          <tr>
            <th><a href="{sort_href('username')}">ID / username</a></th>
            <th><a href="{sort_href('username')}">Username</a></th>
            <th><a href="{sort_href('first_name')}">Ім'я</a></th>
            <th><a href="{sort_href('first_seen_at')}">Реєстрація</a></th>
            <th><a href="{sort_href('last_seen_at')}">Остання активність</a></th>
            <th><a href="{sort_href('balance_uah')}">Баланс</a></th>
            <th><a href="{sort_href('total_spent_uah')}">Витрачено</a></th>
            <th><a href="{sort_href('total_topup_uah')}">Поповнено</a></th>
            <th><a href="{sort_href('turns_total')}">Turns</a></th>
            <th><a href="{sort_href('turns_today')}">Сьогодні</a></th>
            <th><a href="{sort_href('turns_7d')}">7 днів</a></th>
            <th><a href="{sort_href('tokens_in')}">Tokens in</a></th>
            <th><a href="{sort_href('tokens_out')}">Tokens out</a></th>
            <th><a href="{sort_href('favorite_model')}">Улюблена модель</a></th>
            <th>Дія</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </section>
    """
    return _admin_shell(title="Admin · Користувачі", body=body, flash=flash, flash_kind=flash_kind)


def render_admin_user_detail_page(
    detail: dict,
    *,
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    user_id = int(detail["user_id"])
    account_id = detail.get("account_id")
    owned_chats = detail.get("owned_chats") or []
    turns = detail.get("recent_turns") or []
    txs = detail.get("recent_transactions") or []
    topups = detail.get("recent_topups") or []
    settings = detail.get("user_settings") or {}

    stats = f"""
    <section class="panel">
      <div class="meta-grid">
        <div class="stat"><span class="lbl">Користувач</span><div class="val">{_display_user(detail)}</div></div>
        <div class="stat"><span class="lbl">Баланс</span><div class="val">{_fmt_money(detail.get('balance_uah'))} ₴</div></div>
        <div class="stat"><span class="lbl">Витрачено</span><div class="val">{_fmt_money(detail.get('total_spent_uah'))} ₴</div></div>
        <div class="stat"><span class="lbl">Поповнено</span><div class="val">{_fmt_money(detail.get('total_topup_uah'))} ₴</div></div>
        <div class="stat"><span class="lbl">Turns всього</span><div class="val">{_fmt_int(detail.get('turns_total'))}</div></div>
        <div class="stat"><span class="lbl">Turns сьогодні</span><div class="val">{_fmt_int(detail.get('turns_today'))}</div></div>
        <div class="stat"><span class="lbl">Owned chats</span><div class="val">{_fmt_int(detail.get('owned_chats_count'))}</div></div>
        <div class="stat"><span class="lbl">Account</span><div class="val">{html.escape(str(account_id or '—'))}</div></div>
      </div>
    </section>
    """

    chats_html = "".join(
        f"<tr><td class='mono'>{html.escape(str(chat.get('chat_id')))}</td><td>{html.escape(chat.get('tg_chat_type') or '—')}</td><td>{html.escape(chat.get('title') or '—')}</td></tr>"
        for chat in owned_chats
    ) or '<tr><td colspan="3" class="muted">Чатів поки немає.</td></tr>'

    turns_html = "".join(
        f"<tr><td class='mono'>{html.escape(str(turn.get('turn_id') or '—'))}</td><td>{html.escape(turn.get('capability') or '—')}</td><td>{html.escape(turn.get('status') or '—')}</td><td>{_fmt_money(turn.get('total_cost_uah'), places=4)} ₴</td><td>{_fmt_dt(turn.get('created_at'))}</td></tr>"
        for turn in turns
    ) or '<tr><td colspan="5" class="muted">Turns поки немає.</td></tr>'

    txs_html = "".join(
        f"<tr><td>{_fmt_dt(tx.get('created_at'))}</td><td>{html.escape(tx.get('capability') or tx.get('kind') or '—')}</td><td>{html.escape(tx.get('provider') or '—')}</td><td>{html.escape(tx.get('model') or '—')}</td><td>{_fmt_money(tx.get('cost_uah'), places=4)} ₴</td></tr>"
        for tx in txs[:20]
    ) or '<tr><td colspan="5" class="muted">Транзакцій поки немає.</td></tr>'

    topups_html = "".join(
        f"<tr><td>{_fmt_dt(topup.get('created_at'))}</td><td>{html.escape(topup.get('status') or '—')}</td><td>{_fmt_money(topup.get('amount_uah'))} ₴</td><td>{html.escape(topup.get('note') or '—')}</td></tr>"
        for topup in topups
    ) or '<tr><td colspan="4" class="muted">Поповнень поки немає.</td></tr>'

    settings_rows = "".join(
        f"<tr><td class='mono'>{html.escape(str(key))}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in sorted(settings.items())
    ) or '<tr><td colspan="2" class="muted">Персональні налаштування ще не задані.</td></tr>'

    body = f"""
    {stats}
    <div class="grid2">
      <div class="stack">
        <section class="panel">
          <h2>Профіль</h2>
          <table class="data-table">
            <tbody>
              <tr><th>User ID</th><td class="mono">{user_id}</td></tr>
              <tr><th>Username</th><td>{html.escape(detail.get('tg_username') or '—')}</td></tr>
              <tr><th>Ім'я</th><td>{html.escape(detail.get('first_name') or '—')}</td></tr>
              <tr><th>Прізвище</th><td>{html.escape(detail.get('last_name') or '—')}</td></tr>
              <tr><th>Lang</th><td>{html.escape(detail.get('lang_code') or '—')}</td></tr>
              <tr><th>First seen</th><td>{_fmt_dt(detail.get('first_seen_at'))}</td></tr>
              <tr><th>Last seen</th><td>{_fmt_dt(detail.get('last_seen_at'))}</td></tr>
            </tbody>
          </table>
        </section>
        <section class="panel">
          <h2>Останні turns</h2>
          <table class="data-table"><thead><tr><th>Turn</th><th>Capability</th><th>Status</th><th>Cost</th><th>Created</th></tr></thead><tbody>{turns_html}</tbody></table>
        </section>
        <section class="panel">
          <h2>Останні транзакції</h2>
          <table class="data-table"><thead><tr><th>Час</th><th>Capability</th><th>Provider</th><th>Model</th><th>Cost</th></tr></thead><tbody>{txs_html}</tbody></table>
        </section>
      </div>
      <div class="stack">
        <section class="panel">
          <h2>Ручне поповнення</h2>
          <p class="panel-desc">Тимчасовий Stage 4.5A шлях, поки Monobank ще не інтегрований.</p>
          <form method="post" action="/admin/users/{user_id}/credit">
            <label class="field"><span>Сума, ₴</span><input name="amount_uah" inputmode="decimal" placeholder="50.00" required></label>
            <label class="field"><span>Нотатка</span><textarea name="note" placeholder="Причина поповнення, джерело, хто просив" required></textarea></label>
            <button class="btn btn-main" type="submit">Поповнити баланс</button>
          </form>
        </section>
        <section class="panel">
          <h2>Owned chats</h2>
          <table class="data-table"><thead><tr><th>Chat ID</th><th>Тип</th><th>Назва</th></tr></thead><tbody>{chats_html}</tbody></table>
        </section>
        <section class="panel">
          <h2>Останні поповнення</h2>
          <table class="data-table"><thead><tr><th>Час</th><th>Status</th><th>Сума</th><th>Note</th></tr></thead><tbody>{topups_html}</tbody></table>
        </section>
        <section class="panel">
          <h2>User settings</h2>
          <table class="data-table"><thead><tr><th>Ключ</th><th>Значення</th></tr></thead><tbody>{settings_rows}</tbody></table>
        </section>
      </div>
    </div>
    """
    return _admin_shell(title=f"Admin · User {user_id}", body=body, flash=flash, flash_kind=flash_kind)


def render_admin_transactions_page(
    rows: list[dict],
    summary: dict,
    *,
    sort: str,
    direction: str,
    query: str = "",
    capability: str = "",
    provider: str = "",
    model: str = "",
    status: str = "",
    kind: str = "",
    date_from: str = "",
    date_to: str = "",
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    def sort_href(column: str) -> str:
        next_dir = "asc" if sort != column or direction == "desc" else "desc"
        params = {
            "sort": column,
            "dir": next_dir,
            "q": query,
            "capability": capability,
            "provider": provider,
            "model": model,
            "status": status,
            "kind": kind,
            "date_from": date_from,
            "date_to": date_to,
        }
        return "/admin/transactions?" + urlencode(
            {key: value for key, value in params.items() if value}
        )

    metrics = f"""
    <section class="panel">
      <div class="meta-grid">
        <div class="stat"><span class="lbl">Транзакцій</span><div class="val">{_fmt_int(summary.get('total_rows'))}</div></div>
        <div class="stat"><span class="lbl">Сума</span><div class="val">{_fmt_money(summary.get('total_cost_uah'), places=4)} ₴</div></div>
        <div class="stat"><span class="lbl">Tokens in</span><div class="val">{_fmt_int(summary.get('total_tokens_in'))}</div></div>
        <div class="stat"><span class="lbl">Tokens out</span><div class="val">{_fmt_int(summary.get('total_tokens_out'))}</div></div>
        <div class="stat"><span class="lbl">Success</span><div class="val">{_fmt_int(summary.get('success_count'))}</div></div>
        <div class="stat"><span class="lbl">Failed</span><div class="val">{_fmt_int(summary.get('failed_count'))}</div></div>
        <div class="stat"><span class="lbl">Rate limited</span><div class="val">{_fmt_int(summary.get('rate_limited_count'))}</div></div>
        <div class="stat"><span class="lbl">Сер. latency</span><div class="val">{_fmt_int(summary.get('avg_latency_ms'))} ms</div></div>
      </div>
    </section>
    """

    rows_html = ""
    for row in rows:
        user_id = int(row.get("user_id") or 0)
        error_text = (row.get("error_text") or "").strip()
        error_cell = (
            html.escape(error_text[:180] + ("…" if len(error_text) > 180 else ""))
            if error_text
            else "—"
        )
        rows_html += f"""
        <tr>
          <td>{_fmt_dt(row.get("created_at"))}</td>
          <td class="mono">{html.escape(str(row.get("id") or '—'))}</td>
          <td class="mono">{html.escape(str(row.get("turn_id") or '—'))}</td>
          <td><a href="/admin/users/{user_id}">{_display_user(row)}</a></td>
          <td class="mono">{html.escape(str(row.get("chat_id") or '—'))}</td>
          <td>{_display_chat(row)}</td>
          <td>{html.escape(row.get("capability") or row.get("kind") or "—")}</td>
          <td>{html.escape(row.get("provider") or "—")}</td>
          <td>{html.escape(row.get("model") or "—")}</td>
          <td>{html.escape(row.get("status") or "—")}</td>
          <td>{_fmt_int(row.get("tokens_in"))}</td>
          <td>{_fmt_int(row.get("tokens_out"))}</td>
          <td>{_fmt_int(row.get("unit_count"))}</td>
          <td>{_fmt_money(row.get("cost_uah"), places=4)} ₴</td>
          <td>{_fmt_int(row.get("latency_ms"))} ms</td>
          <td title="{html.escape(error_text)}">{error_cell}</td>
        </tr>
        """
    if not rows_html:
        rows_html = '<tr><td colspan="16" class="muted">Нічого не знайдено.</td></tr>'

    body = f"""
    {metrics}
    <section class="panel">
      <h2>Глобальний лог транзакцій</h2>
      <p class="panel-desc">Фільтруй витрати по capability, провайдеру, моделі, статусу і часу. Пошук ловить user id, @username, turn id, chat id і модель.</p>
      <form class="filters" method="get" action="/admin/transactions">
        <input type="hidden" name="sort" value="{html.escape(sort)}">
        <input type="hidden" name="dir" value="{html.escape(direction)}">
        <label class="field">
          <span>Пошук</span>
          <input type="text" name="q" value="{html.escape(query)}" placeholder="user id, @username, turn id, model">
        </label>
        <label class="field">
          <span>Capability</span>
          <input type="text" name="capability" value="{html.escape(capability)}" placeholder="chat_final">
        </label>
        <label class="field">
          <span>Provider</span>
          <input type="text" name="provider" value="{html.escape(provider)}" placeholder="openai / gemini">
        </label>
        <label class="field">
          <span>Model</span>
          <input type="text" name="model" value="{html.escape(model)}" placeholder="gpt-5.4-mini">
        </label>
        <label class="field">
          <span>Status</span>
          <select name="status">
            <option value=""{" selected" if not status else ""}>Будь-який</option>
            <option value="success"{" selected" if status == "success" else ""}>success</option>
            <option value="failed"{" selected" if status == "failed" else ""}>failed</option>
            <option value="rate_limited"{" selected" if status == "rate_limited" else ""}>rate_limited</option>
          </select>
        </label>
        <label class="field">
          <span>Kind</span>
          <select name="kind">
            <option value=""{" selected" if not kind else ""}>Будь-який</option>
            <option value="llm_call"{" selected" if kind == "llm_call" else ""}>llm_call</option>
            <option value="search_api"{" selected" if kind == "search_api" else ""}>search_api</option>
            <option value="tts"{" selected" if kind == "tts" else ""}>tts</option>
            <option value="stt"{" selected" if kind == "stt" else ""}>stt</option>
            <option value="fetch_page"{" selected" if kind == "fetch_page" else ""}>fetch_page</option>
            <option value="other"{" selected" if kind == "other" else ""}>other</option>
          </select>
        </label>
        <label class="field">
          <span>Від дати</span>
          <input type="date" name="date_from" value="{html.escape(date_from)}">
        </label>
        <label class="field">
          <span>До дати</span>
          <input type="date" name="date_to" value="{html.escape(date_to)}">
        </label>
        <button class="btn btn-main" type="submit">Застосувати</button>
      </form>
    </section>
    <section class="panel">
      <table class="data-table">
        <thead>
          <tr>
            <th><a href="{sort_href('created_at')}">Час</a></th>
            <th><a href="{sort_href('id')}">Tx ID</a></th>
            <th>Turn</th>
            <th><a href="{sort_href('user_id')}">Користувач</a></th>
            <th><a href="{sort_href('chat_id')}">Chat ID</a></th>
            <th>Чат</th>
            <th><a href="{sort_href('capability')}">Capability</a></th>
            <th><a href="{sort_href('provider')}">Provider</a></th>
            <th><a href="{sort_href('model')}">Model</a></th>
            <th><a href="{sort_href('status')}">Status</a></th>
            <th><a href="{sort_href('tokens_in')}">In</a></th>
            <th><a href="{sort_href('tokens_out')}">Out</a></th>
            <th>Units</th>
            <th><a href="{sort_href('cost_uah')}">Cost</a></th>
            <th><a href="{sort_href('latency_ms')}">Latency</a></th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </section>
    """
    return _admin_shell(
        title="Admin · Транзакції",
        body=body,
        flash=flash,
        flash_kind=flash_kind,
    )


def render_admin_chats_page(
    rows: list[dict],
    summary: dict,
    *,
    sort: str,
    direction: str,
    query: str = "",
    access_mode: str = "",
    tg_chat_type: str = "",
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    def sort_href(column: str) -> str:
        next_dir = "asc" if sort != column or direction == "desc" else "desc"
        params = {
            "sort": column,
            "dir": next_dir,
            "q": query,
            "access_mode": access_mode,
            "tg_chat_type": tg_chat_type,
        }
        return "/admin/chats?" + urlencode(
            {key: value for key, value in params.items() if value}
        )

    metrics = f"""
    <section class="panel">
      <div class="meta-grid">
        <div class="stat"><span class="lbl">Чатів</span><div class="val">{_fmt_int(summary.get('total_chats'))}</div></div>
        <div class="stat"><span class="lbl">З owner</span><div class="val">{_fmt_int(summary.get('owned_chats'))}</div></div>
        <div class="stat"><span class="lbl">Restricted</span><div class="val">{_fmt_int(summary.get('restricted_chats'))}</div></div>
        <div class="stat"><span class="lbl">Витрата сьогодні</span><div class="val">{_fmt_money(summary.get('total_spent_today_uah'), places=4)} ₴</div></div>
        <div class="stat"><span class="lbl">Витрата всього</span><div class="val">{_fmt_money(summary.get('total_spent_uah'), places=4)} ₴</div></div>
      </div>
    </section>
    """

    rows_html = ""
    for row in rows:
        owner_id = row.get("owner_user_id")
        owner_cell = (
            f'<a href="/admin/users/{int(owner_id)}">{html.escape(row.get("owner_label") or "—")}</a>'
            if owner_id
            else "—"
        )
        rows_html += f"""
        <tr>
          <td class="mono">{html.escape(str(row.get("chat_id") or '—'))}</td>
          <td>{html.escape(row.get("title") or "—")}</td>
          <td>{html.escape(row.get("tg_chat_type") or "—")}</td>
          <td>{owner_cell}</td>
          <td>{html.escape(row.get("access_mode") or "open")}</td>
          <td>{_fmt_money(row.get("per_user_daily_cap_uah"), places=4)} ₴</td>
          <td>{_fmt_money(row.get("per_chat_daily_cap_uah"), places=4)} ₴</td>
          <td>{_fmt_money(row.get("spent_today_uah"), places=4)} ₴</td>
          <td>{_fmt_money(row.get("spent_total_uah"), places=4)} ₴</td>
          <td>{_fmt_dt(row.get("last_turn_at"))}</td>
          <td>{_fmt_int(row.get("allowed_count"))}</td>
          <td>{_fmt_int(row.get("delegated_admin_count"))}</td>
          <td>{_fmt_int(row.get("banned_count"))}</td>
        </tr>
        """
    if not rows_html:
        rows_html = '<tr><td colspan="13" class="muted">Нічого не знайдено.</td></tr>'

    body = f"""
    {metrics}
    <section class="panel">
      <h2>Чати</h2>
      <p class="panel-desc">Список чатів із billing-owner, policy і фактичною витратою. Це базовий operational зріз до окремої деталки чату.</p>
      <form class="filters" method="get" action="/admin/chats">
        <input type="hidden" name="sort" value="{html.escape(sort)}">
        <input type="hidden" name="dir" value="{html.escape(direction)}">
        <label class="field">
          <span>Пошук</span>
          <input type="text" name="q" value="{html.escape(query)}" placeholder="chat id, title, @owner">
        </label>
        <label class="field">
          <span>Access mode</span>
          <select name="access_mode">
            <option value=""{" selected" if not access_mode else ""}>Будь-який</option>
            <option value="open"{" selected" if access_mode == "open" else ""}>open</option>
            <option value="whitelist"{" selected" if access_mode == "whitelist" else ""}>whitelist</option>
            <option value="admins_only"{" selected" if access_mode == "admins_only" else ""}>admins_only</option>
            <option value="owner_only"{" selected" if access_mode == "owner_only" else ""}>owner_only</option>
          </select>
        </label>
        <label class="field">
          <span>Тип чату</span>
          <select name="tg_chat_type">
            <option value=""{" selected" if not tg_chat_type else ""}>Будь-який</option>
            <option value="private"{" selected" if tg_chat_type == "private" else ""}>private</option>
            <option value="group"{" selected" if tg_chat_type == "group" else ""}>group</option>
            <option value="supergroup"{" selected" if tg_chat_type == "supergroup" else ""}>supergroup</option>
            <option value="channel"{" selected" if tg_chat_type == "channel" else ""}>channel</option>
            <option value="unknown"{" selected" if tg_chat_type == "unknown" else ""}>unknown</option>
          </select>
        </label>
        <button class="btn btn-main" type="submit">Застосувати</button>
      </form>
    </section>
    <section class="panel">
      <table class="data-table">
        <thead>
          <tr>
            <th><a href="{sort_href('chat_id')}">Chat ID</a></th>
            <th><a href="{sort_href('title')}">Назва</a></th>
            <th><a href="{sort_href('tg_chat_type')}">Тип</a></th>
            <th><a href="{sort_href('owner')}">Owner</a></th>
            <th><a href="{sort_href('access_mode')}">Mode</a></th>
            <th><a href="{sort_href('per_user_daily_cap_uah')}">User cap</a></th>
            <th><a href="{sort_href('per_chat_daily_cap_uah')}">Chat cap</a></th>
            <th><a href="{sort_href('spent_today_uah')}">Spent today</a></th>
            <th><a href="{sort_href('spent_total_uah')}">Spent total</a></th>
            <th><a href="{sort_href('last_turn_at')}">Остання активність</a></th>
            <th>Allowed</th>
            <th>Delegated</th>
            <th>Banned</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </section>
    """
    return _admin_shell(
        title="Admin · Чати",
        body=body,
        flash=flash,
        flash_kind=flash_kind,
    )


def render_admin_topups_page(
    rows: list[dict],
    summary: dict,
    *,
    sort: str,
    direction: str,
    query: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    def sort_href(column: str) -> str:
        next_dir = "asc" if sort != column or direction == "desc" else "desc"
        params = {
            "sort": column,
            "dir": next_dir,
            "q": query,
            "status": status,
            "date_from": date_from,
            "date_to": date_to,
        }
        return "/admin/topups?" + urlencode(
            {key: value for key, value in params.items() if value}
        )

    metrics = f"""
    <section class="panel">
      <div class="meta-grid">
        <div class="stat"><span class="lbl">Поповнень</span><div class="val">{_fmt_int(summary.get('total_topups'))}</div></div>
        <div class="stat"><span class="lbl">Сума всього</span><div class="val">{_fmt_money(summary.get('total_amount_uah'))} ₴</div></div>
        <div class="stat"><span class="lbl">Успішно</span><div class="val">{_fmt_money(summary.get('success_amount_uah'))} ₴</div></div>
        <div class="stat"><span class="lbl">Manual</span><div class="val">{_fmt_money(summary.get('manual_amount_uah'))} ₴</div></div>
        <div class="stat"><span class="lbl">Pending</span><div class="val">{_fmt_int(summary.get('pending_count'))}</div></div>
      </div>
    </section>
    """

    rows_html = ""
    for row in rows:
        user_id = row.get("user_id")
        user_cell = (
            f'<a href="/admin/users/{int(user_id)}">{_display_user(row)}</a>'
            if user_id
            else "—"
        )
        note = (row.get("note") or "").strip()
        note_cell = html.escape(note[:160] + ("…" if len(note) > 160 else "")) if note else "—"
        rows_html += f"""
        <tr>
          <td>{_fmt_dt(row.get("created_at"))}</td>
          <td class="mono">{html.escape(str(row.get("id") or '—'))}</td>
          <td>{user_cell}</td>
          <td class="mono">{html.escape(str(row.get("account_id") or '—'))}</td>
          <td>{html.escape(row.get("status") or "—")}</td>
          <td>{_fmt_money(row.get("amount_uah"))} ₴</td>
          <td>{_fmt_dt(row.get("paid_at"))}</td>
          <td class="mono">{html.escape(str(row.get("monopay_invoice_id") or '—'))}</td>
          <td title="{html.escape(note)}">{note_cell}</td>
        </tr>
        """
    if not rows_html:
        rows_html = '<tr><td colspan="9" class="muted">Нічого не знайдено.</td></tr>'

    body = f"""
    {metrics}
    <section class="panel">
      <h2>Поповнення</h2>
      <p class="panel-desc">Global log поповнень: ручні admin credits і майбутні Monobank invoice-и. Зараз це головний audit trail для billing topups.</p>
      <form class="filters" method="get" action="/admin/topups">
        <input type="hidden" name="sort" value="{html.escape(sort)}">
        <input type="hidden" name="dir" value="{html.escape(direction)}">
        <label class="field">
          <span>Пошук</span>
          <input type="text" name="q" value="{html.escape(query)}" placeholder="topup id, user id, @username, note, invoice">
        </label>
        <label class="field">
          <span>Status</span>
          <select name="status">
            <option value=""{" selected" if not status else ""}>Будь-який</option>
            <option value="created"{" selected" if status == "created" else ""}>created</option>
            <option value="pending"{" selected" if status == "pending" else ""}>pending</option>
            <option value="success"{" selected" if status == "success" else ""}>success</option>
            <option value="expired"{" selected" if status == "expired" else ""}>expired</option>
            <option value="failed"{" selected" if status == "failed" else ""}>failed</option>
            <option value="manual"{" selected" if status == "manual" else ""}>manual</option>
          </select>
        </label>
        <label class="field">
          <span>Від дати</span>
          <input type="date" name="date_from" value="{html.escape(date_from)}">
        </label>
        <label class="field">
          <span>До дати</span>
          <input type="date" name="date_to" value="{html.escape(date_to)}">
        </label>
        <button class="btn btn-main" type="submit">Застосувати</button>
      </form>
    </section>
    <section class="panel">
      <table class="data-table">
        <thead>
          <tr>
            <th><a href="{sort_href('created_at')}">Створено</a></th>
            <th><a href="{sort_href('id')}">Topup ID</a></th>
            <th><a href="{sort_href('username')}">Користувач</a></th>
            <th>Account</th>
            <th><a href="{sort_href('status')}">Status</a></th>
            <th><a href="{sort_href('amount_uah')}">Сума</a></th>
            <th><a href="{sort_href('paid_at')}">Paid at</a></th>
            <th>Invoice</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </section>
    """
    return _admin_shell(
        title="Admin · Поповнення",
        body=body,
        flash=flash,
        flash_kind=flash_kind,
    )


def render_admin_keys_page(
    rows: list[dict],
    summary: dict,
    *,
    sort: str,
    direction: str,
    query: str = "",
    provider: str = "",
    status: str = "",
    flash: str = "",
    flash_kind: str = "info",
) -> str:
    def sort_href(column: str) -> str:
        next_dir = "asc" if sort != column or direction == "desc" else "desc"
        params = {
            "sort": column,
            "dir": next_dir,
            "q": query,
            "provider": provider,
            "status": status,
        }
        return "/admin/keys?" + urlencode(
            {key: value for key, value in params.items() if value}
        )

    metrics = f"""
    <section class="panel">
      <div class="meta-grid">
        <div class="stat"><span class="lbl">Ключів</span><div class="val">{_fmt_int(summary.get('total_keys'))}</div></div>
        <div class="stat"><span class="lbl">Active</span><div class="val">{_fmt_int(summary.get('active_keys'))}</div></div>
        <div class="stat"><span class="lbl">Disabled</span><div class="val">{_fmt_int(summary.get('disabled_keys'))}</div></div>
        <div class="stat"><span class="lbl">Rate limited</span><div class="val">{_fmt_int(summary.get('rate_limited_keys'))}</div></div>
        <div class="stat"><span class="lbl">Invalid</span><div class="val">{_fmt_int(summary.get('invalid_keys'))}</div></div>
        <div class="stat"><span class="lbl">Requests</span><div class="val">{_fmt_int(summary.get('total_requests'))}</div></div>
        <div class="stat"><span class="lbl">Spent USD</span><div class="val">${_fmt_money(summary.get('total_spent_usd'), places=6)}</div></div>
      </div>
    </section>
    """

    rows_html = ""
    for row in rows:
        key_id = int(row["id"])
        status_value = html.escape(row.get("status") or "—")
        label = html.escape(row.get("label") or "—")
        provider_slug = row.get("provider") or ""
        provider_cell = html.escape(_provider_label(provider_slug))
        masked_key = html.escape(_mask_provider_key(row))
        error_text = (row.get("last_error") or "").strip()
        error_short = (
            html.escape(error_text[:140] + ("…" if len(error_text) > 140 else ""))
            if error_text
            else "—"
        )
        toggle_target = "disabled" if row.get("status") == "active" else "active"
        toggle_label = "Disable" if row.get("status") == "active" else "Enable"
        rows_html += f"""
        <tr>
          <td class="mono">{key_id}</td>
          <td>{provider_cell}</td>
          <td>{label}</td>
          <td class="mono">{masked_key}</td>
          <td><span class="tag">{status_value}</span></td>
          <td>{html.escape(str(row.get("rpm_limit") or "—"))}</td>
          <td>{html.escape(str(row.get("tpm_limit") or "—"))}</td>
          <td>{_fmt_int(row.get("total_requests"))}</td>
          <td>${_fmt_money(row.get("total_spent_usd"), places=6)}</td>
          <td>{_fmt_dt(row.get("last_used_at"))}</td>
          <td title="{html.escape(error_text)}">{error_short}</td>
          <td>{_fmt_dt(row.get("cooldown_until"))}</td>
          <td>
            <form method="post" action="/admin/keys/{key_id}/toggle" style="margin:0; display:inline">
              <input type="hidden" name="target_status" value="{toggle_target}">
              <button class="btn btn-sec" type="submit">{toggle_label}</button>
            </form>
          </td>
        </tr>
        """
    if not rows_html:
        rows_html = '<tr><td colspan="13" class="muted">Ключів не знайдено.</td></tr>'

    provider_options = ['<option value="">Усі провайдери</option>']
    for item in PROVIDERS:
        selected = " selected" if provider == item.slug else ""
        provider_options.append(
            f'<option value="{html.escape(item.slug)}"{selected}>{html.escape(item.label)}</option>'
        )

    body = f"""
    {metrics}
    <div class="grid2">
      <section class="panel">
        <h2>Пул провайдерських ключів</h2>
        <p class="panel-desc">Ключі зберігаються зашифрованими через існуючий billing crypto layer. Ця сторінка потрібна не для перегляду секретів, а для керування ротацією, статусами і пулом, з якого runtime реально бере ключі під час multitenant turns.</p>
        <form class="filters" method="get" action="/admin/keys">
          <input type="hidden" name="sort" value="{html.escape(sort)}">
          <input type="hidden" name="dir" value="{html.escape(direction)}">
          <label class="field">
            <span>Пошук</span>
            <input type="text" name="q" value="{html.escape(query)}" placeholder="id, provider, label, key hash">
          </label>
          <label class="field">
            <span>Provider</span>
            <select name="provider">{''.join(provider_options)}</select>
          </label>
          <label class="field">
            <span>Status</span>
            <select name="status">
              <option value=""{" selected" if not status else ""}>Будь-який</option>
              <option value="active"{" selected" if status == "active" else ""}>active</option>
              <option value="disabled"{" selected" if status == "disabled" else ""}>disabled</option>
              <option value="rate_limited"{" selected" if status == "rate_limited" else ""}>rate_limited</option>
              <option value="invalid"{" selected" if status == "invalid" else ""}>invalid</option>
            </select>
          </label>
          <button class="btn btn-main" type="submit">Застосувати</button>
        </form>
      </section>
      <section class="panel">
        <h2>Додати ключ</h2>
        <p class="panel-desc">API key після збереження більше не показується. У базі зберігаються тільки ciphertext і sha256 fingerprint. Runtime побачить новий ключ одразу після збереження, якщо provider pool для цього провайдера активний.</p>
        <form class="stack" method="post" action="/admin/keys/add">
          <label class="field">
            <span>Provider</span>
            <select name="provider" required>{''.join(provider_options[1:])}</select>
          </label>
          <label class="field">
            <span>Label</span>
            <input type="text" name="label" maxlength="64" placeholder="openai-main-1">
          </label>
          <label class="field">
            <span>API key</span>
            <input type="password" name="api_key" required autocomplete="off" placeholder="sk-... / AIza...">
          </label>
          <label class="field">
            <span>RPM limit</span>
            <input type="number" name="rpm_limit" min="0" placeholder="60">
          </label>
          <label class="field">
            <span>TPM limit</span>
            <input type="number" name="tpm_limit" min="0" placeholder="100000">
          </label>
          <button class="btn btn-main" type="submit">Додати ключ</button>
        </form>
      </section>
    </div>
    <section class="panel">
      <table class="data-table">
        <thead>
          <tr>
            <th><a href="{sort_href('id')}">ID</a></th>
            <th><a href="{sort_href('provider')}">Provider</a></th>
            <th><a href="{sort_href('label')}">Label</a></th>
            <th>Masked key</th>
            <th><a href="{sort_href('status')}">Status</a></th>
            <th><a href="{sort_href('rpm_limit')}">RPM</a></th>
            <th><a href="{sort_href('tpm_limit')}">TPM</a></th>
            <th><a href="{sort_href('total_requests')}">Requests</a></th>
            <th><a href="{sort_href('total_spent_usd')}">Spent USD</a></th>
            <th><a href="{sort_href('last_used_at')}">Last used</a></th>
            <th><a href="{sort_href('last_error_at')}">Last error</a></th>
            <th><a href="{sort_href('cooldown_until')}">Cooldown until</a></th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </section>
    """
    return _admin_shell(
        title="Admin · Ключі",
        body=body,
        flash=flash,
        flash_kind=flash_kind,
    )


def _parse_admin_user_detail_path(path: str) -> int | None:
    match = re.fullmatch(r"/admin/users/(\d+)", path or "")
    return int(match.group(1)) if match else None


def _parse_admin_user_credit_path(path: str) -> int | None:
    match = re.fullmatch(r"/admin/users/(\d+)/credit", path or "")
    return int(match.group(1)) if match else None


def _parse_admin_key_toggle_path(path: str) -> int | None:
    match = re.fullmatch(r"/admin/keys/(\d+)/toggle", path or "")
    return int(match.group(1)) if match else None


def render_login(message: str = "", *, action_path: str = ADMIN_PASSWORD_LOGIN_PATH) -> str:
    flash = f'<div class="login-flash">{html.escape(message)}</div>' if message else ""
    return f"""{_shared_head("Smartest Login")}
<body class="login-body">
<form class="login-card" method="post" action="{html.escape(action_path)}">
  <h1>Smartest<br>Control</h1>
  <p>Увійди в панель керування.</p>
  {flash}
  <label class="field-block"><span>Логін</span><input name="username" autocomplete="username" required></label>
  <label class="field-block"><span>Пароль</span><input type="password" name="password" autocomplete="current-password" required></label>
  <button class="btn btn-primary btn-block" type="submit">Увійти</button>
</form>
</body>
</html>"""


from app.render.portal import (
    _portal_flash_html,
    render_portal_dashboard_page,
    render_portal_history_page,
    render_portal_settings_page,
    render_portal_shell,
    render_portal_topup_page,
    render_portal_turn_page,
    render_user_portal_landing,
)
from app.render.legal import (
    render_privacy_page,
    render_refund_page,
    render_tos_page,
)


def _parse_portal_turn_path(path: str) -> str | None:
    match = re.fullmatch(r"/history/([A-Za-z0-9\-]{4,64})", path or "")
    return match.group(1) if match else None


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
        if parsed.path == ADMIN_PASSWORD_LOGIN_PATH:
            self._send_html(render_login(self._query_param(parsed.query, "message")), head_only=True); return
        if parsed.path == "/login":
            self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
        if parsed.path in {
            "/admin",
            "/admin/config",
            "/admin/users",
            "/admin/transactions",
            "/admin/chats",
            "/admin/topups",
            "/admin/keys",
            "/prompts",
            "/logs",
            "/logs-text",
        } or _parse_admin_user_detail_path(parsed.path):
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            self._send_text("", head_only=True); return
        if parsed.path in {"/", "/history", "/settings", "/topup"} or _parse_portal_turn_path(parsed.path):
            self._send_text("", head_only=True); return
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND); return
        self._send_text("", head_only=True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_text("ok"); return
        if parsed.path.startswith("/static/"):
            self._send_static(parsed.path[len("/static/"):]); return
        if parsed.path in ("/tos", "/privacy", "/refund"):
            user_session = self._current_user_session()
            user = user_session if user_session else None
            if parsed.path == "/tos":
                self._send_html(render_tos_page(user=user)); return
            if parsed.path == "/privacy":
                self._send_html(render_privacy_page(user=user)); return
            self._send_html(render_refund_page(user=user)); return
        if parsed.path == ADMIN_PASSWORD_LOGIN_PATH:
            self._send_html(render_login(self._query_param(parsed.query, "message"))); return
        if parsed.path == "/login":
            self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
        if parsed.path == "/auth/telegram/start":
            self._handle_telegram_login_start(); return
        if parsed.path == "/auth/telegram/callback":
            self._handle_telegram_login_callback(parsed); return
        if parsed.path == "/":
            user_session = self._current_user_session()
            flash = self._query_param(parsed.query, "flash")
            flash_kind = self._query_param(parsed.query, "kind") or "info"
            if not user_session:
                values = read_current_config()
                self._send_portal_landing(values, flash=flash, flash_kind=flash_kind); return
            self._handle_portal_dashboard(user_session, flash=flash, flash_kind=flash_kind); return
        if parsed.path == "/history":
            user_session = self._current_user_session()
            if not user_session:
                self._redirect("/?" + urlencode({"flash": "Спочатку увійди через Telegram.", "kind": "warn"})); return
            self._handle_portal_history(user_session); return
        if parsed.path == "/settings":
            user_session = self._current_user_session()
            if not user_session:
                self._redirect("/?" + urlencode({"flash": "Спочатку увійди через Telegram.", "kind": "warn"})); return
            self._handle_portal_settings(
                user_session,
                flash=self._query_param(parsed.query, "flash"),
                flash_kind=self._query_param(parsed.query, "kind") or "info",
            ); return
        if parsed.path == "/topup":
            user_session = self._current_user_session()
            if not user_session:
                self._redirect("/?" + urlencode({"flash": "Спочатку увійди через Telegram.", "kind": "warn"})); return
            self._handle_portal_topup(
                user_session,
                flash=self._query_param(parsed.query, "flash"),
                flash_kind=self._query_param(parsed.query, "kind") or "info",
            ); return
        portal_turn_ref = _parse_portal_turn_path(parsed.path)
        if portal_turn_ref is not None:
            user_session = self._current_user_session()
            if not user_session:
                self._redirect("/?" + urlencode({"flash": "Спочатку увійди через Telegram.", "kind": "warn"})); return
            self._handle_portal_turn_detail(user_session, portal_turn_ref); return
        if parsed.path == "/admin":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            self._redirect("/admin/users"); return
        if parsed.path == "/admin/config":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            values = read_current_config()
            self._send_html(render_dashboard(values, flash=self._query_param(parsed.query, "flash"), flash_kind=self._query_param(parsed.query, "kind") or "info")); return
        if parsed.path == "/admin/users":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            self._handle_admin_users_page(parsed); return
        if parsed.path == "/admin/transactions":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            self._handle_admin_transactions_page(parsed); return
        if parsed.path == "/admin/chats":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            self._handle_admin_chats_page(parsed); return
        if parsed.path == "/admin/topups":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            self._handle_admin_topups_page(parsed); return
        if parsed.path == "/admin/keys":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            self._handle_admin_keys_page(parsed); return
        user_detail_id = _parse_admin_user_detail_path(parsed.path)
        if user_detail_id is not None:
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            self._handle_admin_user_detail_page(user_detail_id, parsed); return
        if parsed.path == "/prompts":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            values = read_current_config()
            self._send_html(render_prompts_page(values, flash=self._query_param(parsed.query, "flash"), flash_kind=self._query_param(parsed.query, "kind") or "info")); return
        if parsed.path == "/logs":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH); return
            values = read_current_config()
            svc = self._query_param(parsed.query, "service") or MANAGED_BOT_SERVICE
            lines = min(5000, max(50, int(self._query_param(parsed.query, "lines") or "500")))
            source = self._query_param(parsed.query, "source") or "auto"
            contains = self._query_param(parsed.query, "contains")
            trace = self._query_param(parsed.query, "trace")
            chat_id = self._query_param(parsed.query, "chat_id")
            message_id = self._query_param(parsed.query, "message_id")
            capability = self._query_param(parsed.query, "capability")
            level = self._query_param(parsed.query, "level")
            self._send_html(
                render_logs_page(
                    values,
                    service=svc,
                    lines=lines,
                    source=source,
                    contains=contains,
                    trace=trace,
                    chat_id=chat_id,
                    message_id=message_id,
                    capability=capability,
                    level=level,
                )
            ); return
        if parsed.path == "/logs-text":
            if not self._current_admin_session():
                self._send_text("unauthorized", status=HTTPStatus.UNAUTHORIZED); return
            svc = self._query_param(parsed.query, "service") or MANAGED_BOT_SERVICE
            if svc not in (MANAGED_BOT_SERVICE, SELF_SERVICE_NAME):
                svc = MANAGED_BOT_SERVICE
            lines = min(5000, max(50, int(self._query_param(parsed.query, "lines") or "500")))
            source = self._query_param(parsed.query, "source") or "auto"
            contains = self._query_param(parsed.query, "contains")
            trace = self._query_param(parsed.query, "trace")
            chat_id = self._query_param(parsed.query, "chat_id")
            message_id = self._query_param(parsed.query, "message_id")
            capability = self._query_param(parsed.query, "capability")
            level = self._query_param(parsed.query, "level")
            log_text, _, _ = _read_log_text(
                svc,
                lines=lines,
                source=source,
                contains=contains,
                trace=trace,
                chat_id=chat_id,
                message_id=message_id,
                capability=capability,
                level=level,
            )
            self._send_text(log_text); return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/login", ADMIN_PASSWORD_LOGIN_PATH}:
            self._handle_login(); return
        if parsed.path == "/auth/telegram":
            self._handle_telegram_login(); return
        if parsed.path == "/settings":
            user_session = self._current_user_session()
            if not user_session:
                self._redirect("/?" + urlencode({"flash": "Спочатку увійди через Telegram.", "kind": "warn"})); return
            self._handle_portal_settings_update(user_session); return
        if parsed.path == "/topup":
            user_session = self._current_user_session()
            if not user_session:
                self._redirect("/?" + urlencode({"flash": "Спочатку увійди через Telegram.", "kind": "warn"})); return
            self._handle_portal_topup_request(user_session); return
        if parsed.path == "/logout":
            self._clear_user_session(); return
        if parsed.path == "/admin/logout":
            self._clear_admin_session(); return
        if parsed.path == "/save":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH + "?" + urlencode({"message": "Потрібен повторний вхід."})); return
            self._handle_save(); return
        if parsed.path == "/save-prompts":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH + "?" + urlencode({"message": "Потрібен повторний вхід."})); return
            self._handle_save_prompts(); return
        if parsed.path == "/clear-memory":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH + "?" + urlencode({"message": "Потрібен повторний вхід."})); return
            self._handle_clear_memory(); return
        if parsed.path == "/upload-podcast-secret":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH + "?" + urlencode({"message": "РџРѕС‚СЂС–Р±РµРЅ РїРѕРІС‚РѕСЂРЅРёР№ РІС…С–Рґ."})); return
            self._handle_upload_podcast_secret(); return
        if parsed.path == "/check-podcast":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH + "?" + urlencode({"message": "РџРѕС‚СЂС–Р±РµРЅ РїРѕРІС‚РѕСЂРЅРёР№ РІС…С–Рґ."})); return
            self._handle_check_podcast(); return
        if parsed.path == "/admin/keys/add":
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH + "?" + urlencode({"message": "Потрібен повторний вхід."})); return
            self._handle_admin_key_add(); return
        credit_user_id = _parse_admin_user_credit_path(parsed.path)
        if credit_user_id is not None:
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH + "?" + urlencode({"message": "РџРѕС‚СЂС–Р±РµРЅ РїРѕРІС‚РѕСЂРЅРёР№ РІС…С–Рґ."})); return
            self._handle_admin_user_credit(credit_user_id); return
        key_toggle_id = _parse_admin_key_toggle_path(parsed.path)
        if key_toggle_id is not None:
            if not self._current_admin_session():
                self._redirect(ADMIN_PASSWORD_LOGIN_PATH + "?" + urlencode({"message": "Потрібен повторний вхід."})); return
            self._handle_admin_key_toggle(key_toggle_id); return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _body_params(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", "replace")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: vals[-1] if vals else "" for key, vals in parsed.items()}

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", "replace")
        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except Exception as exc:
            raise ValueError("invalid json") from exc
        if not isinstance(payload, dict):
            raise ValueError("json body must be an object")
        return payload

    def _multipart_form(self):
        env = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
        }
        return cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ=env,
            keep_blank_values=True,
        )

    def _query_param(self, query: str, key: str) -> str:
        parsed = parse_qs(query, keep_blank_values=True)
        values = parsed.get(key)
        return values[-1] if values else ""

    def _cookie_morsel(self, cookie_name: str):
        cookie_header = self.headers.get("Cookie", "")
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        return cookie.get(cookie_name)

    def _cookie_session(self, cookie_name: str, secret_key: str) -> dict | None:
        morsel = self._cookie_morsel(cookie_name)
        if not morsel:
            return None
        values = read_current_config()
        secret = values.get(secret_key) or os.getenv(secret_key) or ""
        if not secret:
            return None
        return parse_session_token(morsel.value, secret)

    def _current_user_oauth_session(self) -> dict | None:
        morsel = self._cookie_morsel(USER_OAUTH_COOKIE_NAME)
        if not morsel:
            return None
        values = read_current_config()
        secret = ensure_user_session_secret(values)
        return parse_session_token(morsel.value, secret)

    def _request_origin(self) -> str:
        proto = (self.headers.get("X-Forwarded-Proto") or "").strip() or "http"
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").strip()
        if not host:
            host = f"{HOST}:{PORT}"
        return f"{proto}://{host}"

    def _absolute_url(self, path: str) -> str:
        suffix = path if path.startswith("/") else f"/{path}"
        return f"{self._request_origin()}{suffix}"

    def _current_admin_session(self) -> dict | None:
        session = self._cookie_session(COOKIE_NAME, _session_secret_key())
        if session:
            return session
        user_session = self._current_user_session()
        if not user_session or not user_session.get("is_admin"):
            return None
        return {
            "u": str(user_session.get("username") or f"tg:{user_session.get('user_id')}"),
            "user_id": user_session.get("user_id"),
            "is_portal_admin": True,
        }

    def _current_user_session(self) -> dict | None:
        session = self._cookie_session(USER_COOKIE_NAME, _user_session_secret_key())
        if not session:
            return None
        try:
            user_id = int(session.get("user_id"))
        except Exception:
            return session
        values = read_current_config()
        session["is_admin"] = user_id in admin_tg_user_ids(values)
        return session

    def _current_session(self) -> dict | None:
        return self._current_admin_session()

    def _set_admin_session(self, username: str) -> None:
        values = read_current_config()
        secret = ensure_session_secret(values)
        token = session_token(username, secret)
        self.send_header("Set-Cookie", f"{COOKIE_NAME}={token}; Max-Age={SESSION_MAX_AGE}; Path=/; HttpOnly; SameSite=Lax")

    def _set_user_session(self, payload: dict) -> None:
        values = read_current_config()
        secret = ensure_user_session_secret(values)
        token = user_session_token(
            user_id=int(payload["user_id"]),
            tg_username=str(payload.get("username") or ""),
            display_name=str(payload.get("name") or ""),
            is_admin=bool(payload.get("is_admin")),
            secret=secret,
        )
        self.send_header("Set-Cookie", f"{USER_COOKIE_NAME}={token}; Max-Age={SESSION_MAX_AGE}; Path=/; HttpOnly; SameSite=Lax")

    def _set_user_oauth_session(self, payload: dict) -> None:
        values = read_current_config()
        secret = ensure_user_session_secret(values)
        token = _sign_session_payload(payload, secret)
        self.send_header(
            "Set-Cookie",
            f"{USER_OAUTH_COOKIE_NAME}={token}; Max-Age={USER_OAUTH_MAX_AGE}; Path=/auth/telegram; HttpOnly; SameSite=Lax",
        )

    def _expire_cookie_header(self, cookie_name: str, *, path: str = "/") -> None:
        self.send_header("Set-Cookie", f"{cookie_name}=; Max-Age=0; Path={path}; HttpOnly; SameSite=Lax")

    def _finish_telegram_login_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self._expire_cookie_header(USER_OAUTH_COOKIE_NAME, path="/auth/telegram")
        self.send_header("Location", location)
        self.end_headers()

    def _clear_admin_session(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self._expire_cookie_header(COOKIE_NAME)
        target = (
            "/settings?" + urlencode({"flash": "Адмінський режим завершено.", "kind": "info"})
            if self._current_user_session()
            else ADMIN_PASSWORD_LOGIN_PATH + "?" + urlencode({"message": "Сесію завершено."})
        )
        self.send_header("Location", target)
        self.end_headers()

    def _clear_user_session(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self._expire_cookie_header(USER_COOKIE_NAME)
        self._expire_cookie_header(USER_OAUTH_COOKIE_NAME, path="/auth/telegram")
        self.send_header("Location", "/?" + urlencode({"flash": "Сесію завершено.", "kind": "info"}))
        self.end_headers()

    def _send_portal_landing(self, values: dict[str, str], *, flash: str = "", flash_kind: str = "info") -> None:
        login_nonce = secrets.token_urlsafe(24) if telegram_login_client_id(values) else ""
        content = render_user_portal_landing(
            values,
            flash=flash,
            flash_kind=flash_kind,
            login_nonce=login_nonce,
        )
        encoded = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        if login_nonce:
            self._set_user_oauth_session(
                {
                    "nonce": login_nonce,
                    "exp": int(time.time()) + USER_OAUTH_MAX_AGE,
                }
            )
        else:
            self._expire_cookie_header(USER_OAUTH_COOKIE_NAME, path="/auth/telegram")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    _login_fails: dict[str, list[float]] = {}
    _LOGIN_MAX_ATTEMPTS = 5
    _LOGIN_BLOCK_SEC = 300

    def _handle_login(self) -> None:
        ip = self.client_address[0]
        now = time.time()
        attempts = self._login_fails.get(ip, [])
        attempts = [t for t in attempts if now - t < self._LOGIN_BLOCK_SEC]
        if len(attempts) >= self._LOGIN_MAX_ATTEMPTS:
            self._send_html(render_login("Забагато спроб. Зачекайте 5 хвилин."), status=HTTPStatus.TOO_MANY_REQUESTS)
            return
        params = self._body_params()
        values = read_current_config()
        username = params.get("username", "").strip()
        password = params.get("password", "")
        if username != admin_username(values) or password != admin_password(values):
            attempts.append(now)
            self._login_fails[ip] = attempts
            self._send_html(render_login("Невірний логін або пароль."), status=HTTPStatus.UNAUTHORIZED)
            return
        self._login_fails.pop(ip, None)
        self.send_response(HTTPStatus.SEE_OTHER)
        self._set_admin_session(username)
        self.send_header("Location", "/admin/config?" + urlencode({"flash": "Вхід успішний.", "kind": "info"}))
        self.end_headers()

    def _handle_telegram_login_start(self) -> None:
        self._redirect(
            "/?" + urlencode(
                {
                    "flash": "Портал більше не використовує redirect flow. Натисни кнопку Telegram Login на головній сторінці.",
                    "kind": "info",
                }
            )
        )

    def _handle_telegram_login_callback(self, parsed) -> None:
        values = read_current_config()
        if not telegram_login_client_id(values):
            self._redirect(
                "/?" + urlencode(
                    {
                        "flash": "Telegram Login ще не сконфігурований. Додай валідний TG_BOT_TOKEN або TELEGRAM_LOGIN_CLIENT_ID.",
                        "kind": "warn",
                    }
                )
            )
            return
        self._redirect(
            "/?" + urlencode(
                {
                    "flash": "Portal більше не використовує callback redirect. Натисни кнопку Telegram Login на головній сторінці.",
                    "kind": "info",
                }
            )
        )

    def _handle_telegram_login(self) -> None:
        values = read_current_config()
        client_id = telegram_login_client_id(values)
        if not client_id:
            self._send_json({"ok": False, "message": "Telegram Login ще не сконфігурований."}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        ip = self.client_address[0]
        now = time.time()
        attempts = self._login_fails.get(ip, [])
        attempts = [t for t in attempts if now - t < self._LOGIN_BLOCK_SEC]
        if len(attempts) >= self._LOGIN_MAX_ATTEMPTS:
            self._send_json({"ok": False, "message": "Забагато невдалих спроб входу. Зачекай кілька хвилин."}, status=HTTPStatus.TOO_MANY_REQUESTS)
            return
        try:
            body = self._json_body()
        except ValueError:
            self._send_json({"ok": False, "message": "Некоректне тіло запиту."}, status=HTTPStatus.BAD_REQUEST)
            return
        id_token = str(body.get("id_token") or "").strip()
        oauth_state = self._current_user_oauth_session()
        login_nonce = str((oauth_state or {}).get("nonce") or "").strip()
        if not id_token:
            self._send_json({"ok": False, "message": "Telegram Login не повернув id_token."}, status=HTTPStatus.BAD_REQUEST)
            return
        if not login_nonce:
            self._send_json({"ok": False, "message": "Login nonce втрачений або прострочений. Перезавантаж сторінку і спробуй ще раз."}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            claims = verify_telegram_token(id_token, client_id, expected_nonce=login_nonce)
        except Exception as exc:
            attempts.append(now)
            self._login_fails[ip] = attempts
            logger.warning("portal.telegram_login_failed error=%s", exc)
            self._send_json({"ok": False, "message": f"Telegram login не завершився: {exc}"}, status=HTTPStatus.UNAUTHORIZED)
            return
        self._login_fails.pop(ip, None)
        telegram_user_id = claims.get("id") or claims.get("sub")
        try:
            user_id = int(telegram_user_id)
        except Exception:
            self._send_json({"ok": False, "message": "Telegram token не містить валідного user id."}, status=HTTPStatus.UNAUTHORIZED)
            return
        username = str(claims.get("preferred_username") or "").lstrip("@")
        display_name = str(claims.get("name") or username or f"user {user_id}")
        identity = asyncio.run(
            ensure_portal_identity(
                user_id=user_id,
                tg_username=username or None,
                first_name=display_name or None,
                lang_code=None,
                phone_number=(str(claims.get("phone_number") or "").strip() or None),
            )
        )
        session_payload = {
            "user_id": user_id,
            "username": username,
            "name": display_name,
            "is_admin": user_id in admin_tg_user_ids(values),
        }
        self.send_response(HTTPStatus.OK)
        self._set_user_session(session_payload)
        self._expire_cookie_header(USER_OAUTH_COOKIE_NAME, path="/auth/telegram")
        payload = {
            "ok": True,
            "redirect": "/?" + urlencode(
                {
                    "flash": (
                        f"Вхід успішний. Акаунт #{identity['account']['account_id']}"
                        if identity.get("account")
                        else "Вхід успішний."
                    ),
                    "kind": "ok",
                }
            ),
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _handle_portal_dashboard(self, user_session: dict, *, flash: str = "", flash_kind: str = "info") -> None:
        dashboard = asyncio.run(get_portal_dashboard(int(user_session["user_id"])))
        if not dashboard:
            self._send_html(render_user_portal_landing(read_current_config(), flash="Портал ще не готовий для цього користувача.", flash_kind="warn")); return
        dashboard["user"]["is_admin"] = bool(user_session.get("is_admin"))
        self._send_html(
            render_portal_dashboard_page(
                dashboard["user"],
                dashboard["account"],
                dashboard["turns"],
                dashboard["settings"],
                flash=flash,
                flash_kind=flash_kind,
            )
        )

    def _handle_portal_history(self, user_session: dict) -> None:
        payload = asyncio.run(get_portal_history(int(user_session["user_id"])))
        if not payload:
            self._redirect("/?" + urlencode({"flash": "Портал ще не готовий для цього користувача.", "kind": "warn"})); return
        payload["user"]["is_admin"] = bool(user_session.get("is_admin"))
        self._send_html(render_portal_history_page(payload["user"], payload["account"], payload["turns"]))

    def _handle_portal_turn_detail(self, user_session: dict, turn_ref: str) -> None:
        payload = asyncio.run(get_portal_turn_detail(int(user_session["user_id"]), turn_ref))
        if not payload:
            self._redirect("/history?" + urlencode({"flash": "Turn не знайдено.", "kind": "warn"})); return
        payload["user"]["is_admin"] = bool(user_session.get("is_admin"))
        self._send_html(
            render_portal_turn_page(
                payload["user"],
                payload["turn"],
                payload["transactions"],
                payload["ambiguous_matches"],
            )
        )

    def _handle_portal_settings(self, user_session: dict, *, flash: str = "", flash_kind: str = "info") -> None:
        payload = asyncio.run(get_portal_settings(int(user_session["user_id"])))
        if not payload:
            self._redirect("/?" + urlencode({"flash": "Портал ще не готовий для цього користувача.", "kind": "warn"})); return
        payload["user"]["is_admin"] = bool(user_session.get("is_admin"))
        self._send_html(
            render_portal_settings_page(
                payload["user"],
                payload["account"],
                payload["settings"],
                payload["catalog"],
                flash=flash,
                flash_kind=flash_kind,
            )
        )

    def _handle_portal_settings_update(self, user_session: dict) -> None:
        params = self._body_params()
        model_choices = {
            group.slug: params.get(f"model_group_{group.slug}", "").strip()
            for group in MODEL_GROUPS
        }
        voice_id = params.get("voice_id", "").strip()
        persona_slug = params.get("persona_slug", "").strip()
        try:
            asyncio.run(
                update_portal_settings(
                    int(user_session["user_id"]),
                    model_choices=model_choices,
                    voice_id=voice_id,
                    persona_slug=persona_slug,
                )
            )
        except ValueError as exc:
            self._handle_portal_settings(user_session, flash=str(exc), flash_kind="warn")
            return
        self._redirect(
            "/settings?"
            + urlencode(
                {
                    "flash": "Персональні налаштування збережено.",
                    "kind": "ok",
                }
            )
        )

    def _handle_portal_topup(self, user_session: dict, *, flash: str = "", flash_kind: str = "info") -> None:
        payload = asyncio.run(get_portal_topups(int(user_session["user_id"])))
        if not payload:
            self._redirect("/?" + urlencode({"flash": "Портал ще не готовий для цього користувача.", "kind": "warn"})); return
        payload["user"]["is_admin"] = bool(user_session.get("is_admin"))
        self._send_html(
            render_portal_topup_page(
                payload["user"],
                payload["account"],
                payload["topups"],
                flash=flash,
                flash_kind=flash_kind,
            )
        )

    def _handle_portal_topup_request(self, user_session: dict) -> None:
        params = self._body_params()
        amount_uah = params.get("amount_uah", "").strip()
        note = params.get("note", "").strip()
        try:
            payload = asyncio.run(
                create_portal_topup_request(
                    int(user_session["user_id"]),
                    amount_uah=amount_uah,
                    note=note,
                )
            )
        except ValueError as exc:
            self._handle_portal_topup(user_session, flash=str(exc), flash_kind="warn")
            return
        created = payload.get("topup") or {}
        self._redirect(
            "/topup?"
            + urlencode(
                {
                    "flash": (
                        f"Запит на поповнення #{created.get('id')} створено. "
                        "Поки що це manual queue для адміністратора, не автоматична оплата."
                    ),
                    "kind": "ok",
                }
            )
        )

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
        values_before = read_current_config()
        gb = values_before.get("PROVIDER_GEMINI_THINKING_BUDGET", "0")
        updates["PROVIDER_GEMINI_THINKING_BUDGET"] = gb

        # Global / advanced fields
        for f in GLOBAL_FIELDS:
            updates[f.key] = params.get(f.key, "").strip()

        updates["PODCAST_NOTEBOOKLM_ENABLED"] = _podcast_enabled_from_params(params)
        updates["PODCAST_NOTEBOOKLM_PROJECT_ID"] = params.get("PODCAST_NOTEBOOKLM_PROJECT_ID", "").strip()
        updates["PODCAST_NOTEBOOKLM_LOCATION"] = params.get("PODCAST_NOTEBOOKLM_LOCATION", "").strip() or "global"

        # Access
        updates["SMARTEST_ADMIN_USERNAME"] = params.get("SMARTEST_ADMIN_USERNAME", "").strip()
        updates["SMARTEST_ADMIN_PASSWORD"] = params.get("SMARTEST_ADMIN_PASSWORD", "").strip()

        # Capabilities
        for cap in CAPABILITIES:
            prov, model, adapter = _normalized_capability_binding(
                cap,
                values_before,
                provider=params.get(capability_field_key(cap.slug, "PROVIDER"), "").strip(),
                model=params.get(capability_field_key(cap.slug, "MODEL"), "").strip(),
            )
            custom_key = params.get(capability_field_key(cap.slug, "API_KEY"), "").strip()
            reasoning_enabled = (
                "1"
                if params.get(capability_field_key(cap.slug, "REASONING_ENABLED"), "").strip() == "1"
                and can_reason(prov, model)
                else ""
            )
            reasoning_effort = params.get(
                capability_field_key(cap.slug, "REASONING_EFFORT"),
                "",
            ).strip().lower()
            if reasoning_effort not in {"low", "medium", "high"}:
                reasoning_effort = "medium"

            updates[capability_field_key(cap.slug, "PROVIDER")] = prov
            updates[capability_field_key(cap.slug, "MODEL")] = model
            updates[capability_field_key(cap.slug, "ADAPTER")] = adapter
            updates[capability_field_key(cap.slug, "REASONING_ENABLED")] = reasoning_enabled
            updates[capability_field_key(cap.slug, "REASONING_EFFORT")] = reasoning_effort
            if custom_key:
                updates[capability_field_key(cap.slug, "API_KEY")] = custom_key

        # Preserve credentials
        if not updates.get(_admin_username_key()):
            updates[_admin_username_key()] = values_before.get(_admin_username_key()) or "admin"
        if not updates.get(_admin_password_key()):
            updates[_admin_password_key()] = values_before.get(_admin_password_key()) or "admin"
        if _session_secret_key() not in values_before:
            updates[_session_secret_key()] = ensure_session_secret(values_before)
        if _user_session_secret_key() not in values_before:
            updates[_user_session_secret_key()] = ensure_user_session_secret(values_before)

        write_env_updates(ENV_PATH, updates)

        restarted = False
        if params.get("restart_bot") == "1":
            ok, _ = restart_service(MANAGED_BOT_SERVICE)
            restarted = ok

        flash = "Конфіг збережено."
        if params.get("restart_bot") == "1":
            flash += " Бот перезапущено." if restarted else " Рестарт не підтверджено."

        self._redirect("/admin/config?" + urlencode({
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
        self._redirect("/admin/config?" + urlencode({
            "flash": (
                "Пам'ять бота очищено для всіх чатів."
                if ok
                else "Не вдалося очистити пам'ять бота."
            ),
            "kind": "info" if ok else "error",
        }))

    def _handle_upload_podcast_secret(self) -> None:
        form = self._multipart_form()
        values_before = read_current_config()
        enabled = (
            "1"
            if form.getfirst("PODCAST_NOTEBOOKLM_ENABLED", "") == "1"
            else values_before.get("PODCAST_NOTEBOOKLM_ENABLED", "")
        )
        project_id = (
            form.getfirst("PODCAST_NOTEBOOKLM_PROJECT_ID", "")
            or values_before.get("PODCAST_NOTEBOOKLM_PROJECT_ID", "")
        ).strip()
        location = (
            form.getfirst("PODCAST_NOTEBOOKLM_LOCATION", "")
            or values_before.get("PODCAST_NOTEBOOKLM_LOCATION", "global")
        ).strip() or "global"
        upload = (
            form["PODCAST_NOTEBOOKLM_SECRET_FILE"]
            if "PODCAST_NOTEBOOKLM_SECRET_FILE" in form
            else None
        )
        if upload is None or not getattr(upload, "file", None):
            self._redirect("/admin/config?" + urlencode({
                "flash": "JSON service account не завантажено.",
                "kind": "error",
            }))
            return

        file_bytes = upload.file.read() or b""
        if not file_bytes:
            self._redirect("/admin/config?" + urlencode({
                "flash": "JSON service account порожній або не прочитався.",
                "kind": "error",
            }))
            return

        try:
            info, secret_path = store_service_account_secret(file_bytes, project_id or None)
            resolved_project_id = project_id or info.project_id
            health = podcast_healthcheck(secret_path, resolved_project_id, location)
        except Exception as exc:
            logger.error("admin.podcast_sa_upload_failed: %s", exc, exc_info=True)
            self._redirect("/admin/config?" + urlencode({
                "flash": "Не вдалося зберегти або перевірити service account JSON. Перевірте файл і спробуйте ще.",
                "kind": "error",
            }))
            return

        updates = _podcast_status_updates(
            health,
            enabled=enabled,
            project_id=resolved_project_id,
            location=location,
            secret_path=str(secret_path),
        )
        write_env_updates(ENV_PATH, updates)
        self._redirect("/admin/config?" + urlencode({
            "flash": "JSON завантажено. " + health.message,
            "kind": "info" if health.ready else "error",
        }))

    def _handle_check_podcast(self) -> None:
        params = self._body_params()
        values_before = read_current_config()
        enabled = _podcast_enabled_from_params(params) or values_before.get(
            "PODCAST_NOTEBOOKLM_ENABLED",
            "",
        )
        project_id = (
            params.get("PODCAST_NOTEBOOKLM_PROJECT_ID", "").strip()
            or values_before.get("PODCAST_NOTEBOOKLM_PROJECT_ID", "").strip()
        )
        location = (
            params.get("PODCAST_NOTEBOOKLM_LOCATION", "").strip()
            or values_before.get("PODCAST_NOTEBOOKLM_LOCATION", "global").strip()
            or "global"
        )
        secret_path = values_before.get("PODCAST_NOTEBOOKLM_SECRET_PATH", "").strip()
        if not secret_path:
            self._redirect("/admin/config?" + urlencode({
                "flash": "Спочатку завантаж service account JSON для NotebookLM.",
                "kind": "error",
            }))
            return

        health = podcast_healthcheck(secret_path, project_id, location)
        updates = _podcast_status_updates(
            health,
            enabled=enabled,
            project_id=project_id,
            location=location,
            secret_path=secret_path,
        )
        write_env_updates(ENV_PATH, updates)
        self._redirect("/admin/config?" + urlencode({
            "flash": health.message,
            "kind": "info" if health.ready else "error",
        }))

    def _handle_admin_users_page(self, parsed) -> None:
        sort = self._query_param(parsed.query, "sort") or "last_seen_at"
        direction = self._query_param(parsed.query, "dir") or "desc"
        query = self._query_param(parsed.query, "q")
        rows = asyncio.run(
            list_users_with_stats(
                sort=sort,
                direction=direction,
                query=query,
                limit=250,
            )
        )
        sort, direction = normalize_user_sort(sort, direction)
        self._send_html(
            render_admin_users_page(
                rows,
                sort=sort,
                direction=direction,
                query=query,
                flash=self._query_param(parsed.query, "flash"),
                flash_kind=self._query_param(parsed.query, "kind") or "info",
            )
        )

    def _handle_admin_user_detail_page(self, user_id: int, parsed) -> None:
        detail = asyncio.run(get_user_admin_detail(user_id))
        if not detail:
            self.send_error(HTTPStatus.NOT_FOUND, f"user {user_id} not found")
            return
        self._send_html(
            render_admin_user_detail_page(
                detail,
                flash=self._query_param(parsed.query, "flash"),
                flash_kind=self._query_param(parsed.query, "kind") or "info",
            )
        )

    def _handle_admin_transactions_page(self, parsed) -> None:
        sort = self._query_param(parsed.query, "sort") or "created_at"
        direction = self._query_param(parsed.query, "dir") or "desc"
        filters = {
            "query": self._query_param(parsed.query, "q"),
            "capability": self._query_param(parsed.query, "capability"),
            "provider": self._query_param(parsed.query, "provider"),
            "model": self._query_param(parsed.query, "model"),
            "status": self._query_param(parsed.query, "status"),
            "kind": self._query_param(parsed.query, "kind"),
            "date_from": self._query_param(parsed.query, "date_from"),
            "date_to": self._query_param(parsed.query, "date_to"),
        }
        rows = asyncio.run(
            list_transactions_with_stats(
                sort=sort,
                direction=direction,
                limit=500,
                **filters,
            )
        )
        summary = asyncio.run(get_transactions_summary(**filters))
        sort, direction = normalize_transaction_sort(sort, direction)
        self._send_html(
            render_admin_transactions_page(
                rows,
                summary,
                sort=sort,
                direction=direction,
                query=filters["query"],
                capability=filters["capability"],
                provider=filters["provider"],
                model=filters["model"],
                status=filters["status"],
                kind=filters["kind"],
                date_from=filters["date_from"],
                date_to=filters["date_to"],
                flash=self._query_param(parsed.query, "flash"),
                flash_kind=self._query_param(parsed.query, "kind") or "info",
            )
        )

    def _handle_admin_chats_page(self, parsed) -> None:
        sort = self._query_param(parsed.query, "sort") or "last_turn_at"
        direction = self._query_param(parsed.query, "dir") or "desc"
        filters = {
            "query": self._query_param(parsed.query, "q"),
            "access_mode": self._query_param(parsed.query, "access_mode"),
            "tg_chat_type": self._query_param(parsed.query, "tg_chat_type"),
        }
        rows = asyncio.run(
            list_chats_with_stats(
                sort=sort,
                direction=direction,
                limit=500,
                **filters,
            )
        )
        summary = asyncio.run(get_chats_summary(**filters))
        sort, direction = normalize_chat_sort(sort, direction)
        self._send_html(
            render_admin_chats_page(
                rows,
                summary,
                sort=sort,
                direction=direction,
                query=filters["query"],
                access_mode=filters["access_mode"],
                tg_chat_type=filters["tg_chat_type"],
                flash=self._query_param(parsed.query, "flash"),
                flash_kind=self._query_param(parsed.query, "kind") or "info",
            )
        )

    def _handle_admin_topups_page(self, parsed) -> None:
        sort = self._query_param(parsed.query, "sort") or "created_at"
        direction = self._query_param(parsed.query, "dir") or "desc"
        filters = {
            "query": self._query_param(parsed.query, "q"),
            "status": self._query_param(parsed.query, "status"),
            "date_from": self._query_param(parsed.query, "date_from"),
            "date_to": self._query_param(parsed.query, "date_to"),
        }
        rows = asyncio.run(
            list_topups_with_stats(
                sort=sort,
                direction=direction,
                limit=500,
                **filters,
            )
        )
        summary = asyncio.run(get_topups_summary(**filters))
        sort, direction = normalize_topup_sort(sort, direction)
        self._send_html(
            render_admin_topups_page(
                rows,
                summary,
                sort=sort,
                direction=direction,
                query=filters["query"],
                status=filters["status"],
                date_from=filters["date_from"],
                date_to=filters["date_to"],
                flash=self._query_param(parsed.query, "flash"),
                flash_kind=self._query_param(parsed.query, "kind") or "info",
            )
        )

    def _handle_admin_keys_page(self, parsed) -> None:
        sort = self._query_param(parsed.query, "sort") or "provider"
        direction = self._query_param(parsed.query, "dir") or "asc"
        filters = {
            "query": self._query_param(parsed.query, "q"),
            "provider": self._query_param(parsed.query, "provider"),
            "status": self._query_param(parsed.query, "status"),
        }
        rows = asyncio.run(
            list_provider_keys_with_stats(
                sort=sort,
                direction=direction,
                limit=500,
                **filters,
            )
        )
        summary = asyncio.run(get_provider_keys_summary(**filters))
        sort, direction = normalize_key_sort(sort, direction)
        self._send_html(
            render_admin_keys_page(
                rows,
                summary,
                sort=sort,
                direction=direction,
                query=filters["query"],
                provider=filters["provider"],
                status=filters["status"],
                flash=self._query_param(parsed.query, "flash"),
                flash_kind=self._query_param(parsed.query, "kind") or "info",
            )
        )

    def _handle_admin_key_add(self) -> None:
        params = self._body_params()
        provider = (params.get("provider") or "").strip()
        label = (params.get("label") or "").strip() or None
        api_key = (params.get("api_key") or "").strip()

        rpm_raw = (params.get("rpm_limit") or "").strip()
        tpm_raw = (params.get("tpm_limit") or "").strip()
        rpm_limit = int(rpm_raw) if rpm_raw.isdigit() else None
        tpm_limit = int(tpm_raw) if tpm_raw.isdigit() else None

        known_providers = {provider_def.slug for provider_def in PROVIDERS}
        if provider not in known_providers:
            self._redirect(
                "/admin/keys?" + urlencode({"flash": "Невідомий provider для key pool.", "kind": "warn"})
            )
            return
        if not api_key:
            self._redirect(
                "/admin/keys?" + urlencode({"flash": "API key обов'язковий.", "kind": "warn"})
            )
            return

        try:
            key_id = asyncio.run(
                register_provider_key(
                    provider=provider,
                    raw_key=api_key,
                    label=label,
                    rpm_limit=rpm_limit,
                    tpm_limit=tpm_limit,
                )
            )
        except Exception as exc:
            logger.exception("admin.key_add_failed provider=%s error=%s", provider, exc)
            self._redirect(
                "/admin/keys?" + urlencode({"flash": f"Не вдалося додати ключ: {exc}", "kind": "warn"})
            )
            return

        self._redirect(
            "/admin/keys?" + urlencode(
                {
                    "flash": f"Ключ для {_provider_label(provider)} збережено. key_id={key_id}.",
                    "kind": "ok",
                }
            )
        )

    def _handle_admin_key_toggle(self, key_id: int) -> None:
        params = self._body_params()
        target_status = (params.get("target_status") or "").strip().lower()
        if target_status not in {"active", "disabled"}:
            self._redirect(
                "/admin/keys?" + urlencode({"flash": "Некоректний target_status для ключа.", "kind": "warn"})
            )
            return

        row = asyncio.run(get_provider_key(int(key_id)))
        if not row:
            self._redirect(
                "/admin/keys?" + urlencode({"flash": f"Ключ {key_id} не знайдено.", "kind": "warn"})
            )
            return

        try:
            asyncio.run(set_key_status(int(key_id), target_status))
        except Exception as exc:
            logger.exception("admin.key_toggle_failed key_id=%s target_status=%s error=%s", key_id, target_status, exc)
            self._redirect(
                "/admin/keys?" + urlencode({"flash": f"Не вдалося змінити статус ключа: {exc}", "kind": "warn"})
            )
            return

        self._redirect(
            "/admin/keys?" + urlencode(
                {
                    "flash": f"Статус ключа {key_id} змінено на {target_status}.",
                    "kind": "ok",
                }
            )
        )

    def _handle_admin_user_credit(self, user_id: int) -> None:
        params = self._body_params()
        amount_raw = (params.get("amount_uah") or "").replace(",", ".").strip()
        note = (params.get("note") or "").strip()
        session = self._current_session() or {}
        actor = str(session.get("u") or "admin")
        try:
            amount = Decimal(amount_raw)
        except Exception:
            amount = Decimal("0")
        if amount <= 0:
            self._redirect(
                f"/admin/users/{user_id}?"
                + urlencode({"flash": "Некоректна сума поповнення.", "kind": "warn"})
            )
            return
        if not note:
            self._redirect(
                f"/admin/users/{user_id}?"
                + urlencode({"flash": "Нотатка обов'язкова для ручного поповнення.", "kind": "warn"})
            )
            return
        try:
            result = asyncio.run(
                credit_account_admin(
                    user_id=user_id,
                    amount_uah=amount,
                    note=note,
                    actor=actor,
                )
            )
        except Exception as exc:
            logger.exception("admin.credit_failed user_id=%s error=%s", user_id, exc)
            self._redirect(
                f"/admin/users/{user_id}?"
                + urlencode({"flash": f"Поповнення не вдалося: {exc}", "kind": "warn"})
            )
            return

        username = result["user"].get("tg_username")
        label = f"@{username}" if username else f"user {user_id}"
        self._redirect(
            f"/admin/users/{user_id}?"
            + urlencode(
                {
                    "flash": (
                        f"Баланс {label} поповнено на {_fmt_money(result['amount_uah'])} ₴. "
                        f"Новий баланс: {_fmt_money(result['new_balance_uah'])} ₴."
                    ),
                    "kind": "ok",
                }
            )
        )

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

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_static(self, rel_path: str) -> None:
        clean = (rel_path or "").lstrip("/")
        if not clean or ".." in clean.split("/"):
            self.send_error(HTTPStatus.NOT_FOUND); return
        target = (STATIC_ROOT / clean).resolve()
        try:
            target.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND); return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND); return
        suffix = target.suffix.lower()
        ctype = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".ico": "image/x-icon",
        }.get(suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    setup_logging("smartest-admin", LOG_LEVEL, force=True)
    logger.info("admin.boot env_path=%s host=%s port=%s", ENV_PATH, HOST, PORT)
    values = read_current_config()
    if _admin_username_key() not in values or _admin_password_key() not in values:
        write_env_updates(ENV_PATH, {
            _admin_username_key(): values.get(_admin_username_key()) or "admin",
            _admin_password_key(): values.get(_admin_password_key()) or "admin",
        })
    current = read_current_config()
    ensure_session_secret(current)
    ensure_user_session_secret(read_current_config())
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
