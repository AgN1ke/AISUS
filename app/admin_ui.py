from __future__ import annotations

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

PROVIDER_OPTIONS = [
    "openai",
    "gemini",
    "anthropic",
    "deepseek",
    "mistral",
    "xai",
    "perplexity",
    "tavily",
    "exa",
    "brave",
    "serper",
    "bing",
]

ADAPTER_OPTIONS = [
    "openai_chat",
    "openai_vision",
    "gemini_generate_content",
]


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
    datalist: str | None = None


@dataclass(frozen=True)
class CapabilityDef:
    slug: str
    title: str
    help_text: str


PROVIDER_FIELDS = [
    FieldDef(
        "PROVIDER_OPENAI_API_KEY",
        "OpenAI API key",
        input_type="password",
        help_text="Ключ для OpenAI-compatible текстових і reasoning capability.",
    ),
    FieldDef(
        "PROVIDER_OPENAI_BASE_URL",
        "OpenAI base URL",
        placeholder="https://api.openai.com/v1",
    ),
    FieldDef(
        "PROVIDER_DEEPSEEK_API_KEY",
        "DeepSeek API key",
        input_type="password",
        help_text="Підійде для текстових capability через OpenAI-compatible adapter.",
    ),
    FieldDef(
        "PROVIDER_DEEPSEEK_BASE_URL",
        "DeepSeek base URL",
        placeholder="https://api.deepseek.com",
    ),
    FieldDef(
        "PROVIDER_GEMINI_API_KEY",
        "Gemini API key",
        input_type="password",
        help_text="Ключ для native Gemini transport і grounded search.",
    ),
    FieldDef(
        "PROVIDER_GEMINI_BASE_URL",
        "Gemini base URL",
        placeholder="https://generativelanguage.googleapis.com/v1beta",
    ),
    FieldDef(
        "PROVIDER_GEMINI_THINKING_BUDGET",
        "Gemini thinking budget",
        placeholder="0",
        help_text="Для `gemini-2.5-flash` зазвичай лишаємо 0.",
    ),
    FieldDef(
        "PROVIDER_ANTHROPIC_API_KEY",
        "Anthropic API key",
        input_type="password",
    ),
    FieldDef(
        "PROVIDER_MISTRAL_API_KEY",
        "Mistral API key",
        input_type="password",
    ),
    FieldDef(
        "PROVIDER_XAI_API_KEY",
        "xAI API key",
        input_type="password",
    ),
    FieldDef(
        "PROVIDER_TAVILY_API_KEY",
        "Tavily API key",
        input_type="password",
        help_text="Окремий web search provider.",
    ),
    FieldDef(
        "PROVIDER_PERPLEXITY_API_KEY",
        "Perplexity API key",
        input_type="password",
        help_text="Опційний research/search provider, якщо хочеш окремий synthesized search path.",
    ),
    FieldDef(
        "PROVIDER_EXA_API_KEY",
        "Exa API key",
        input_type="password",
        help_text="Пошук для docs, papers і technical research.",
    ),
    FieldDef(
        "PROVIDER_BRAVE_API_KEY",
        "Brave Search API key",
        input_type="password",
        help_text="Cheap raw search fallback.",
    ),
    FieldDef(
        "PROVIDER_SERPER_API_KEY",
        "Serper API key",
        input_type="password",
        help_text="Google search API layer.",
    ),
    FieldDef(
        "PROVIDER_BING_API_KEY",
        "Bing API key",
        input_type="password",
        help_text="Fallback search provider, якщо є ключ.",
    ),
]

GLOBAL_FIELDS = [
    FieldDef(
        "DEFAULT_LLM_PROVIDER",
        "Провайдер за замовчуванням",
        placeholder="openai",
        datalist="providers",
        help_text="Працює як fallback, якщо capability-specific provider не заданий.",
    ),
    FieldDef(
        "SEARCH_GEMINI_MODEL",
        "Gemini модель для пошуку",
        placeholder="gemini-2.5-flash",
        help_text="Використовується grounded search layer.",
    ),
    FieldDef(
        "SEARCH_OPENAI_MODEL",
        "OpenAI модель для grounded fallback",
        placeholder="gpt-5",
        help_text="Використовується як сильний fallback, якщо raw search providers недоступні.",
    ),
    FieldDef(
        "SEARCH_PROFILE_GENERAL_ORDER",
        "Search order: general",
        placeholder="perplexity_search,openai_search,brave_search,gemini_search,tavily,serper,bing,bing_html,ddg",
    ),
    FieldDef(
        "SEARCH_PROFILE_NEWS_ORDER",
        "Search order: news",
        placeholder="perplexity_search,openai_search,brave_search,gemini_search,tavily,serper,bing,bing_html,ddg",
    ),
    FieldDef(
        "SEARCH_PROFILE_DOCS_ORDER",
        "Search order: docs",
        placeholder="exa_search,tavily,openai_search,brave_search,gemini_search,bing_html,ddg",
    ),
    FieldDef(
        "SEARCH_PROFILE_RESEARCH_PAPER_ORDER",
        "Search order: research paper",
        placeholder="exa_search,perplexity_search,openai_search,brave_search,gemini_search,bing_html,ddg",
    ),
    FieldDef(
        "OPENAI_GPT_MODEL",
        "Legacy OpenAI model",
        placeholder="gpt-5.4-mini",
        help_text="Сумісний fallback для старих env-гілок.",
    ),
    FieldDef(
        "OPENAI_BASE_URL",
        "Legacy OpenAI base URL",
        placeholder="https://api.openai.com/v1",
    ),
]

ACCESS_FIELDS = [
    FieldDef("SMARTEST_ADMIN_USERNAME", "Логін панелі"),
    FieldDef(
        "SMARTEST_ADMIN_PASSWORD",
        "Пароль панелі",
        input_type="password",
        help_text="Після зміни новий логін/пароль застосуються для наступних входів.",
    ),
]

CAPABILITIES = [
    CapabilityDef(
        "chat_final",
        "Фінальна текстова відповідь",
        "Головна модель, яка формує звичайну відповідь користувачу.",
    ),
    CapabilityDef(
        "planner_reasoning",
        "Planner / Router",
        "Мала модель control-plane, яка вирішує маршрут виконання.",
    ),
    CapabilityDef(
        "agent_reasoning",
        "Tool Agent",
        "Стара tool-call гілка, якщо вона ще використовується для reasoning.",
    ),
    CapabilityDef(
        "search_query_composer",
        "Search Query Composer",
        "Модель, що збирає пошуковий запит із діалогового зрізу.",
    ),
    CapabilityDef(
        "search_web",
        "Search Provider Override",
        "Не для LLM, а для жорсткого override search provider через env, якщо треба.",
    ),
    CapabilityDef(
        "search_evaluator",
        "Search Evaluator",
        "Оцінює якість evidence і вирішує, чи потрібен retry.",
    ),
    CapabilityDef(
        "search_synthesis",
        "Search Final Responder",
        "Збирає фінальну відповідь на основі джерел і page evidence.",
    ),
    CapabilityDef(
        "vision_image",
        "Image Understanding",
        "Розпізнавання і опис зображень, мемів, скрінів.",
    ),
    CapabilityDef(
        "video_understanding",
        "Video Understanding",
        "Обробка відео після витягу кадрів і транскрипту.",
    ),
    CapabilityDef(
        "stt_voice",
        "Voice / STT",
        "Текстовий аналіз голосових та аудіо повідомлень.",
    ),
    CapabilityDef(
        "document_context",
        "Document Context",
        "Робота з документами й текстовими вкладеннями.",
    ),
    CapabilityDef(
        "memory_summary",
        "Memory Summary",
        "Стискання історії в довготривалі підсумки.",
    ),
]


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
        quote = value[0]
        inner = value[1:-1]
        if quote == '"':
            return bytes(inner, "utf-8").decode("unicode_escape")
        return inner.replace("\\'", "'")
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
        lines.append(
            EnvLine(
                kind="entry",
                raw=raw_line,
                key=key,
                value=_parse_env_value(raw_value),
            )
        )
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


def ensure_session_secret(values: dict[str, str]) -> str:
    secret = values.get(_session_secret_key()) or ""
    if secret:
        return secret
    secret = secrets.token_urlsafe(32)
    write_env_updates(ENV_PATH, {_session_secret_key(): secret})
    return secret


def admin_username(values: dict[str, str]) -> str:
    return (
        values.get(_admin_username_key()) or os.getenv(_admin_username_key()) or "admin"
    )


def admin_password(values: dict[str, str]) -> str:
    return (
        values.get(_admin_password_key()) or os.getenv(_admin_password_key()) or "admin"
    )


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


def systemctl_text(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["systemctl", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        logger.warning("admin.systemctl_failed args=%s error=%s", args, exc)
        return "unknown"
    return (proc.stdout or proc.stderr or "unknown").strip()


def service_status(service_name: str) -> str:
    status = systemctl_text("is-active", service_name)
    return status or "unknown"


def restart_service(service_name: str) -> tuple[bool, str]:
    output = systemctl_text("restart", service_name)
    ok = service_status(service_name) == "active"
    return ok, output


def read_current_config() -> dict[str, str]:
    return env_map_from_lines(read_env_lines(ENV_PATH))


def capability_field_key(slug: str, suffix: str) -> str:
    return f"CAPABILITY_{slug.upper()}_{suffix}"


def render_datalist(datalist_id: str, options: list[str]) -> str:
    items = "".join(
        f'<option value="{html.escape(item)}"></option>' for item in options
    )
    return f'<datalist id="{html.escape(datalist_id)}">{items}</datalist>'


def render_input(field: FieldDef, value: str) -> str:
    data_attr = f' list="{html.escape(field.datalist)}"' if field.datalist else ""
    placeholder = html.escape(field.placeholder)
    escaped_value = html.escape(value or "")
    help_text = (
        f'<p class="field-help">{html.escape(field.help_text)}</p>'
        if field.help_text
        else ""
    )
    input_class = "secret-input" if field.input_type == "password" else "text-input"
    toggle = (
        '<button class="toggle-secret" type="button" data-toggle-secret>Показати</button>'
        if field.input_type == "password"
        else ""
    )
    return (
        '<label class="field">'
        f'<span class="field-label">{html.escape(field.label)}</span>'
        '<span class="field-control">'
        f'<input class="{input_class}" type="{field.input_type}" name="{html.escape(field.key)}" '
        f'value="{escaped_value}" placeholder="{placeholder}"{data_attr}>'
        f"{toggle}"
        "</span>"
        f"{help_text}"
        "</label>"
    )


def render_capability_card(capability: CapabilityDef, values: dict[str, str]) -> str:
    provider_key = capability_field_key(capability.slug, "PROVIDER")
    adapter_key = capability_field_key(capability.slug, "ADAPTER")
    model_key = capability_field_key(capability.slug, "MODEL")
    provider_field = FieldDef(provider_key, "Провайдер", datalist="providers")
    adapter_field = FieldDef(adapter_key, "Адаптер", datalist="adapters")
    model_field = FieldDef(model_key, "Модель")
    inputs = "".join(
        [
            render_input(provider_field, values.get(provider_key, "")),
            render_input(adapter_field, values.get(adapter_key, "")),
            render_input(model_field, values.get(model_key, "")),
        ]
    )
    return (
        '<section class="capability-card">'
        f"<h3>{html.escape(capability.title)}</h3>"
        f'<p class="capability-help">{html.escape(capability.help_text)}</p>'
        f"{inputs}"
        "</section>"
    )


def render_dashboard(
    values: dict[str, str], flash: str = "", flash_kind: str = "info"
) -> str:
    bot_status = service_status(MANAGED_BOT_SERVICE)
    admin_status = service_status(SELF_SERVICE_NAME)
    env_mtime = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ENV_PATH.stat().st_mtime))
        if ENV_PATH.exists()
        else "ще не створено"
    )
    flash_html = (
        f'<div class="flash flash-{html.escape(flash_kind)}">{html.escape(flash)}</div>'
        if flash
        else ""
    )
    provider_fields_html = "".join(
        render_input(field, values.get(field.key, "")) for field in PROVIDER_FIELDS
    )
    global_fields_html = "".join(
        render_input(field, values.get(field.key, "")) for field in GLOBAL_FIELDS
    )
    access_fields_html = "".join(
        render_input(field, values.get(field.key, "")) for field in ACCESS_FIELDS
    )
    capability_cards = "".join(
        render_capability_card(item, values) for item in CAPABILITIES
    )
    providers_datalist = render_datalist("providers", PROVIDER_OPTIONS)
    adapters_datalist = render_datalist("adapters", ADAPTER_OPTIONS)

    return f"""<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Smartest Control</title>
  <style>
    :root {{
      --bg: #f3ead9;
      --paper: rgba(255, 248, 236, 0.88);
      --ink: #1f1d19;
      --muted: #655d4d;
      --line: rgba(59, 45, 30, 0.14);
      --accent: #bf4b2c;
      --accent-2: #204d46;
      --ok: #2c6b44;
      --warn: #935a14;
      --shadow: 0 24px 60px rgba(52, 36, 18, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(191,75,44,0.22), transparent 32%),
        radial-gradient(circle at bottom right, rgba(32,77,70,0.18), transparent 28%),
        linear-gradient(135deg, #efe1c4 0%, #f7f0e3 42%, #e8dcc5 100%);
    }}
    .shell {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 28px 18px 48px;
    }}
    .hero {{
      display: grid;
      gap: 18px;
      grid-template-columns: 1.2fr 0.8fr;
      align-items: end;
      margin-bottom: 24px;
    }}
    .hero-card, .status-card, .panel, .capability-card {{
      background: var(--paper);
      backdrop-filter: blur(12px);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
    }}
    .hero-card {{
      padding: 28px;
    }}
    .hero-card h1 {{
      margin: 0 0 10px;
      font-size: clamp(2rem, 4vw, 3.4rem);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }}
    .hero-card p {{
      margin: 0;
      color: var(--muted);
      max-width: 62ch;
      font-size: 1rem;
      line-height: 1.55;
    }}
    .status-grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: 1fr 1fr;
    }}
    .status-card {{
      padding: 20px;
    }}
    .status-label {{
      display: block;
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      margin-bottom: 8px;
    }}
    .status-value {{
      font-size: 1.2rem;
      font-weight: 700;
    }}
    .status-active {{ color: var(--ok); }}
    .status-other {{ color: var(--warn); }}
    .flash {{
      margin-bottom: 20px;
      padding: 14px 16px;
      border-radius: 16px;
      font-weight: 600;
    }}
    .flash-info {{
      background: rgba(32,77,70,0.12);
      color: var(--accent-2);
      border: 1px solid rgba(32,77,70,0.18);
    }}
    .flash-error {{
      background: rgba(191,75,44,0.12);
      color: #8b2e14;
      border: 1px solid rgba(191,75,44,0.18);
    }}
    .toolbar {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 18px;
    }}
    .toolbar-actions {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .btn {{
      border: 0;
      border-radius: 999px;
      padding: 14px 20px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform 0.16s ease, opacity 0.16s ease;
    }}
    .btn:hover {{ transform: translateY(-1px); }}
    .btn-primary {{
      color: #fff7ef;
      background: linear-gradient(135deg, var(--accent), #d96c44);
    }}
    .btn-secondary {{
      color: var(--ink);
      background: rgba(255,255,255,0.7);
      border: 1px solid var(--line);
    }}
    .panel {{
      padding: 22px;
      margin-bottom: 20px;
    }}
    .panel h2 {{
      margin: 0 0 12px;
      font-size: 1.15rem;
      letter-spacing: -0.02em;
    }}
    .panel p {{
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.5;
    }}
    .field-grid {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    }}
    .capability-grid {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    }}
    .capability-card {{
      padding: 18px;
      animation: rise 0.35s ease both;
    }}
    .capability-card h3 {{
      margin: 0 0 6px;
      font-size: 1rem;
    }}
    .capability-help {{
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 0.93rem;
      line-height: 1.45;
    }}
    .field {{
      display: block;
    }}
    .field + .field {{
      margin-top: 14px;
    }}
    .field-label {{
      display: block;
      margin-bottom: 8px;
      font-weight: 700;
      font-size: 0.92rem;
    }}
    .field-control {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
    }}
    .text-input, .secret-input {{
      width: 100%;
      border: 1px solid rgba(59,45,30,0.18);
      border-radius: 14px;
      background: rgba(255,255,255,0.82);
      padding: 12px 14px;
      font: inherit;
      color: var(--ink);
    }}
    .field-help {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 0.85rem;
      line-height: 1.45;
    }}
    .toggle-secret {{
      border: 1px solid rgba(59,45,30,0.18);
      background: rgba(255,255,255,0.7);
      color: var(--ink);
      padding: 11px 14px;
      border-radius: 14px;
      font: inherit;
      cursor: pointer;
    }}
    .check {{
      display: inline-flex;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-weight: 600;
    }}
    .muted {{
      color: var(--muted);
      font-size: 0.94rem;
    }}
    @keyframes rise {{
      from {{ opacity: 0; transform: translateY(8px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    @media (max-width: 980px) {{
      .hero {{ grid-template-columns: 1fr; }}
      .status-grid {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 620px) {{
      .shell {{ padding: 18px 14px 34px; }}
      .status-grid {{ grid-template-columns: 1fr; }}
      .field-control {{ grid-template-columns: 1fr; }}
      .toolbar {{ align-items: stretch; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="hero-card">
        <h1>Smartest Control</h1>
        <p>Це окремий конфігураційний контур для твого бота. Тут зібрані capability-моделі, provider keys і пошукові ключі в одному місці. Збереження пише прямо в <code>{html.escape(str(ENV_PATH))}</code>, а бот можна одразу перезапустити після оновлення.</p>
      </div>
      <div class="status-grid">
        <div class="status-card">
          <span class="status-label">Smartest Bot</span>
          <div class="status-value {"status-active" if bot_status == "active" else "status-other"}">{html.escape(bot_status)}</div>
        </div>
        <div class="status-card">
          <span class="status-label">Admin Service</span>
          <div class="status-value {"status-active" if admin_status == "active" else "status-other"}">{html.escape(admin_status)}</div>
        </div>
        <div class="status-card">
          <span class="status-label">Env File</span>
          <div class="status-value">{html.escape(env_mtime)}</div>
        </div>
        <div class="status-card">
          <span class="status-label">Managed Service</span>
          <div class="status-value">{html.escape(MANAGED_BOT_SERVICE)}</div>
        </div>
      </div>
    </section>
    {flash_html}
    <form method="post" action="/save">
      <div class="toolbar">
        <div class="toolbar-actions">
          <button class="btn btn-primary" type="submit">Зберегти конфіг</button>
          <label class="check">
            <input type="checkbox" name="restart_bot" value="1" checked>
            <span>Після збереження перезапустити бота</span>
          </label>
        </div>
        <div class="toolbar-actions">
          <span class="muted">Сесія логіну зберігається cookie до 30 днів.</span>
          <button class="btn btn-secondary" type="submit" formaction="/logout" formmethod="post">Вийти</button>
        </div>
      </div>
      <section class="panel">
        <h2>Глобальні Параметри</h2>
        <p>Fallback-провайдер, legacy сумісність і search-модель, яка використовується grounded retrieval шаром.</p>
        <div class="field-grid">{global_fields_html}</div>
      </section>
      <section class="panel">
        <h2>Provider Keys І Endpoints</h2>
        <p>Тут лежать секрети й base URL для провайдерів. Capability нижче лише посилаються на ці провайдери.</p>
        <div class="field-grid">{provider_fields_html}</div>
      </section>
      <section class="panel">
        <h2>Capability Bindings</h2>
        <p>Для кожної функції бота можна окремо вибрати провайдера, adapter class і саму модель.</p>
        <div class="capability-grid">{capability_cards}</div>
      </section>
      <section class="panel">
        <h2>Доступ До Панелі</h2>
        <p>Можна змінити логін і пароль адмінки. Поточна сесія не злетить одразу, але новий вхід уже перевірятиметься за оновленими даними.</p>
        <div class="field-grid">{access_fields_html}</div>
      </section>
    </form>
  </div>
  {providers_datalist}
  {adapters_datalist}
  <script>
    document.querySelectorAll('[data-toggle-secret]').forEach((button) => {{
      button.addEventListener('click', () => {{
        const input = button.parentElement.querySelector('input');
        const hidden = input.type === 'password';
        input.type = hidden ? 'text' : 'password';
        button.textContent = hidden ? 'Сховати' : 'Показати';
      }});
    }});
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
    :root {{
      --bg: #efe1c4;
      --paper: rgba(255, 248, 236, 0.9);
      --ink: #1f1d19;
      --muted: #6a624f;
      --accent: #bf4b2c;
      --line: rgba(59,45,30,0.14);
      --shadow: 0 30px 80px rgba(44, 28, 10, 0.16);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(191,75,44,0.2), transparent 30%),
        radial-gradient(circle at bottom right, rgba(32,77,70,0.16), transparent 26%),
        linear-gradient(145deg, #f4e8cf 0%, #fbf6ec 55%, #eadfc9 100%);
      padding: 18px;
    }}
    .card {{
      width: min(100%, 430px);
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 28px;
      box-shadow: var(--shadow);
      padding: 28px;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: clamp(2rem, 5vw, 2.8rem);
      line-height: 0.94;
      letter-spacing: -0.04em;
    }}
    p {{
      margin: 0 0 20px;
      color: var(--muted);
      line-height: 1.55;
    }}
    .field {{
      display: block;
      margin-top: 14px;
    }}
    .field span {{
      display: block;
      margin-bottom: 8px;
      font-weight: 700;
      font-size: 0.92rem;
    }}
    input {{
      width: 100%;
      border: 1px solid rgba(59,45,30,0.18);
      border-radius: 14px;
      background: rgba(255,255,255,0.84);
      padding: 13px 14px;
      font: inherit;
      color: var(--ink);
    }}
    button {{
      width: 100%;
      margin-top: 18px;
      border: 0;
      border-radius: 999px;
      padding: 14px 18px;
      font: inherit;
      font-weight: 700;
      color: #fff7ef;
      background: linear-gradient(135deg, var(--accent), #d96c44);
      cursor: pointer;
    }}
    .login-flash {{
      margin-bottom: 16px;
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(191,75,44,0.12);
      color: #8b2e14;
      border: 1px solid rgba(191,75,44,0.18);
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <form class="card" method="post" action="/login">
    <h1>Smartest<br>Control</h1>
    <p>Увійди в панель керування конфігом. Після входу сесія зберігається cookie, тому не треба логінитися заново при кожному відкритті сторінки.</p>
    {flash}
    <label class="field">
      <span>Логін</span>
      <input name="username" autocomplete="username" required>
    </label>
    <label class="field">
      <span>Пароль</span>
      <input type="password" name="password" autocomplete="current-password" required>
    </label>
    <button type="submit">Увійти</button>
  </form>
</body>
</html>"""


class SmartestAdminHandler(BaseHTTPRequestHandler):
    server_version = "SmartestAdmin/1.0"

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s | %s", self.address_string(), fmt % args)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_text("ok", head_only=True)
            return
        if parsed.path == "/login":
            self._send_html(
                render_login(self._query_param(parsed.query, "message")),
                head_only=True,
            )
            return
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        session = self._current_session()
        if not session:
            self._redirect("/login")
            return
        values = read_current_config()
        flash = self._query_param(parsed.query, "flash")
        kind = self._query_param(parsed.query, "kind") or "info"
        self._send_html(
            render_dashboard(values, flash=flash, flash_kind=kind),
            head_only=True,
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_text("ok")
            return
        if parsed.path == "/login":
            self._send_html(render_login(self._query_param(parsed.query, "message")))
            return
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        session = self._current_session()
        if not session:
            self._redirect("/login")
            return
        values = read_current_config()
        flash = self._query_param(parsed.query, "flash")
        kind = self._query_param(parsed.query, "kind") or "info"
        self._send_html(render_dashboard(values, flash=flash, flash_kind=kind))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self._handle_login()
            return
        if parsed.path == "/logout":
            self._clear_session()
            return
        if parsed.path == "/save":
            if not self._current_session():
                self._redirect(
                    "/login?" + urlencode({"message": "Потрібен повторний вхід."})
                )
                return
            self._handle_save()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _body_params(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", "replace")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}

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
        secret = (
            values.get(_session_secret_key()) or os.getenv(_session_secret_key()) or ""
        )
        if not secret:
            return None
        return parse_session_token(morsel.value, secret)

    def _set_session(self, username: str) -> None:
        values = read_current_config()
        secret = ensure_session_secret(values)
        token = session_token(username, secret)
        cookie = f"{COOKIE_NAME}={token}; Max-Age={SESSION_MAX_AGE}; Path=/; HttpOnly; SameSite=Lax"
        self.send_header("Set-Cookie", cookie)

    def _clear_session(self) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header(
            "Set-Cookie",
            f"{COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax",
        )
        self.send_header(
            "Location", "/login?" + urlencode({"message": "Сесію завершено."})
        )
        self.end_headers()

    def _handle_login(self) -> None:
        params = self._body_params()
        values = read_current_config()
        username = params.get("username", "").strip()
        password = params.get("password", "")
        if username != admin_username(values) or password != admin_password(values):
            self._send_html(
                render_login("Невірний логін або пароль."),
                status=HTTPStatus.UNAUTHORIZED,
            )
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self._set_session(username)
        self.send_header(
            "Location",
            "/?" + urlencode({"flash": "Вхід успішний.", "kind": "info"}),
        )
        self.end_headers()

    def _handle_save(self) -> None:
        params = self._body_params()
        updates: dict[str, str] = {}
        for field in PROVIDER_FIELDS + GLOBAL_FIELDS + ACCESS_FIELDS:
            updates[field.key] = params.get(field.key, "").strip()
        for capability in CAPABILITIES:
            for suffix in ("PROVIDER", "ADAPTER", "MODEL"):
                key = capability_field_key(capability.slug, suffix)
                updates[key] = params.get(key, "").strip()
        values_before = read_current_config()
        if not updates.get(_admin_username_key()):
            updates[_admin_username_key()] = (
                values_before.get(_admin_username_key()) or "admin"
            )
        if not updates.get(_admin_password_key()):
            updates[_admin_password_key()] = (
                values_before.get(_admin_password_key()) or "admin"
            )
        if _session_secret_key() not in values_before:
            updates[_session_secret_key()] = ensure_session_secret(values_before)
        write_env_updates(ENV_PATH, updates)
        restarted = False
        if params.get("restart_bot") == "1":
            ok, _ = restart_service(MANAGED_BOT_SERVICE)
            restarted = ok
        flash = "Конфіг збережено."
        if params.get("restart_bot") == "1":
            flash += (
                " Бот перезапущено."
                if restarted
                else " Конфіг збережено, але рестарт бота не підтверджено."
            )
        self._redirect(
            "/?"
            + urlencode(
                {
                    "flash": flash,
                    "kind": "info"
                    if restarted or params.get("restart_bot") != "1"
                    else "error",
                }
            )
        )

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _send_html(
        self,
        content: str,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        head_only: bool = False,
    ) -> None:
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if not head_only:
            self.wfile.write(encoded)

    def _send_text(
        self,
        content: str,
        status: HTTPStatus = HTTPStatus.OK,
        *,
        head_only: bool = False,
    ) -> None:
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
        write_env_updates(
            ENV_PATH,
            {
                _admin_username_key(): values.get(_admin_username_key()) or "admin",
                _admin_password_key(): values.get(_admin_password_key()) or "admin",
            },
        )
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
