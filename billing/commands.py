from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Awaitable, Callable, Optional

from adapters.base import MessageGeometry, UnifiedMessage
from billing.context import BillingContext
from core.env import capability_model, capability_provider, provider_api_key, vocalizer_voice
from core.model_preferences import (
    MODEL_GROUPS,
    ModelGroupDef,
    group_by_slug,
)
from core.prompts import current_persona_slug
from core.user_preferences import PERSONA_PRESETS, VOICE_OPTIONS, persona_preset, voice_option
from db.accounts_repository import create_account, get_account, get_account_by_owner
from db.chats_repository import (
    ensure_chat_policy,
    get_chat,
    get_chat_policy,
    remove_chat_access,
    update_chat_policy,
    upsert_chat_access,
)
from db.keypool_repository import list_provider_keys
from db.topups_repository import create_topup
from db.transactions_repository import (
    find_turns_for_account,
    get_latest_turn_for_account,
    get_transactions_for_turn,
    list_turns_for_account,
    sum_chat_spent_today,
)
from db.users_repository import (
    get_user_by_username,
    get_user_settings,
    set_user_setting,
    upsert_user,
)

logger = logging.getLogger(__name__)

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
except Exception:  # pragma: no cover - PTB may be unavailable in narrow unit tests
    InlineKeyboardButton = None
    InlineKeyboardMarkup = None
    Update = Any

_MIN_TOPUP_UAH = Decimal("50.00")
_MODEL_CALLBACK_PREFIX = "mtmodel"
_TEXT_ONLY_SETTINGS_LINK = "https://smartest.klawa.top"
_SUPPORTED_COMMANDS = {
    "/start",
    "/balance",
    "/topup",
    "/mode",
    "/allow",
    "/ban",
    "/unban",
    "/cap",
    "/settings",
    "/model",
}


@dataclass
class CommandResult:
    handled: bool
    response_text: str | None
    capability: str
    route: str = "command"
    finalize_status: str = "completed"
    response_markup: Any | None = None
    edit_origin: bool = False


CommandHandler = Callable[[UnifiedMessage, MessageGeometry, str, Optional[BillingContext]], Awaitable[CommandResult]]


def parse_command(text: str | None, bot_username: str | None) -> tuple[str, str] | None:
    normalized = (text or "").strip()
    if not normalized.startswith("/"):
        return None
    command_token, _, args = normalized.partition(" ")
    base, at, suffix = command_token.partition("@")
    if at:
        expected = (bot_username or "").strip().lstrip("@").lower()
        if not expected or suffix.strip().lower() != expected:
            return None
    command = base.strip().lower()
    if command not in _SUPPORTED_COMMANDS:
        return None
    return command, args.strip()


def _parse_amount(raw: str | None) -> Decimal | None:
    cleaned = str(raw or "").strip().replace(",", ".")
    if not cleaned:
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _format_money(value: Decimal | float | int | None) -> str:
    amount = Decimal(str(value or 0))
    return f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _short_turn_id(turn_id: str | None, *, size: int = 8) -> str:
    normalized = (turn_id or "").strip()
    if not normalized:
        return "—"
    return normalized[:size]


def _turn_status_label(status: str | None) -> str:
    normalized = (status or "").strip().lower()
    mapping = {
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "budget_blocked": "budget_blocked",
        "policy_blocked": "policy_blocked",
    }
    return mapping.get(normalized, normalized or "unknown")


def _format_tx_usage(row: dict) -> str:
    tokens_in = int(row.get("tokens_in") or 0)
    tokens_out = int(row.get("tokens_out") or 0)
    unit_count = int(row.get("unit_count") or 0)
    parts: list[str] = []
    if tokens_in or tokens_out:
        parts.append(f"{tokens_in} in / {tokens_out} out tok")
    if unit_count:
        parts.append(f"{unit_count} units")
    return ", ".join(parts) if parts else "no usage counters"


def _render_turn_breakdown(turn: dict, transactions: list[dict]) -> str:
    lines = [
        "💳 <b>Breakdown turn-а</b>",
        f"Turn: <code>{turn.get('turn_id') or '—'}</code>",
        f"Сумарно: <b>{_format_money(turn.get('total_cost_uah'))} грн</b>",
        f"Статус: <code>{_turn_status_label(turn.get('status'))}</code>",
    ]
    route = (turn.get("route") or "").strip()
    capability = (turn.get("capability") or "").strip()
    if route:
        lines.append(f"Route: <code>{route}</code>")
    if capability:
        lines.append(f"Capability: <code>{capability}</code>")
    user_text = (turn.get("user_message_text") or "").strip()
    if user_text:
        excerpt = user_text[:280]
        if len(user_text) > 280:
            excerpt += "…"
        lines.append(f"Текст: <i>{excerpt}</i>")
    lines.append("")
    if not transactions:
        lines.append("Для цього turn-а ще немає sub-транзакцій.")
        return "\n".join(lines)
    lines.append("Sub-транзакції:")
    for row in transactions:
        capability_name = (row.get("capability") or row.get("kind") or "unknown").strip()
        provider = (row.get("provider") or "—").strip()
        model = (row.get("model") or "—").strip()
        kind = (row.get("kind") or "other").strip()
        status = (row.get("status") or "unknown").strip()
        cost = _format_money(row.get("cost_uah"))
        usage = _format_tx_usage(row)
        lines.append(f"• <code>{capability_name}</code> — {provider} / {model}")
        lines.append(
            f"  {kind}, {status}, {usage}, <b>{cost} грн</b>"
        )
        error_text = (row.get("error_text") or "").strip()
        if error_text:
            lines.append(f"  error: <code>{error_text[:180]}</code>")
    return "\n".join(lines)


async def _resolve_turn_for_balance(account_id: int, turn_ref: str) -> tuple[dict | None, str | None]:
    normalized = (turn_ref or "").strip()
    if not normalized:
        return None, "Формат: <code>/balance last</code> або <code>/balance turn &lt;id&gt;</code>."
    matches = await find_turns_for_account(account_id, normalized, limit=6)
    if not matches:
        return None, f"Не знайшов turn <code>{normalized}</code> у межах твого акаунта."
    exact = [row for row in matches if str(row.get('turn_id') or '').strip() == normalized]
    if exact:
        return exact[0], None
    if len(matches) == 1:
        return matches[0], None
    variants = ", ".join(f"<code>{_short_turn_id(row.get('turn_id'), size=12)}</code>" for row in matches[:5])
    return None, (
        f"Префікс <code>{normalized}</code> неоднозначний. Уточни turn id. "
        f"Збіги: {variants}"
    )


def _supports_inline(msg: UnifiedMessage) -> bool:
    return bool(msg.platform == "ptb" and InlineKeyboardMarkup and InlineKeyboardButton)


async def _provider_available(provider_slug: str) -> bool:
    if provider_api_key(provider_slug):
        return True
    try:
        rows = await list_provider_keys(provider_slug)
    except Exception as exc:
        logger.warning("billing.commands.list_provider_keys_failed provider=%s error=%s", provider_slug, exc)
        return False
    return any((row.get("status") or "").strip().lower() in {"active", "disabled", "rate_limited"} for row in rows)


def _default_group_choice(group: ModelGroupDef) -> tuple[str, str]:
    capability = group.capabilities[0]
    return capability_provider(capability), capability_model(capability)


def _current_group_choice(settings: dict[str, str], group: ModelGroupDef) -> tuple[str, str]:
    provider = (settings.get(group.provider_setting_key) or "").strip().lower()
    model = (settings.get(group.model_setting_key) or "").strip()
    if provider and model and model in group.providers.get(provider, tuple()):
        return provider, model
    return _default_group_choice(group)


def _default_voice_choice() -> str:
    configured = vocalizer_voice().strip().lower()
    if voice_option(configured):
        return configured
    return VOICE_OPTIONS[0].voice_id


def _current_voice_choice(settings: dict[str, str]) -> str:
    configured = (settings.get("voice_id") or "").strip().lower()
    if voice_option(configured):
        return configured
    return _default_voice_choice()


def _current_persona_choice(settings: dict[str, str]) -> str:
    configured = (settings.get("persona_slug") or "").strip().lower()
    if persona_preset(configured):
        return configured
    runtime_slug = current_persona_slug()
    if persona_preset(runtime_slug):
        return runtime_slug
    return "default"


async def _available_providers_for_group(group: ModelGroupDef) -> list[str]:
    visible: list[str] = []
    for provider in group.providers.keys():
        if await _provider_available(provider):
            visible.append(provider)
    return visible


def _provider_title(provider_slug: str) -> str:
    titles = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "gemini": "Gemini",
        "deepseek": "DeepSeek",
        "mistral": "Mistral",
        "xai": "xAI",
    }
    return titles.get(provider_slug, provider_slug)


def _model_root_text(
    user_settings: dict[str, str],
    *,
    include_policy_text: str | None = None,
    headline: str = "Персональний вибір моделей",
    status_line: str | None = None,
) -> str:
    lines = [f"⚙️ <b>{headline}</b>"]
    if status_line:
        lines.append(status_line)
    lines.append(
        "Налаштування персональні: вони керують тим, якою моделлю бот відповідає саме тобі, "
        "не ламаючи інших людей у чаті."
    )
    lines.append("")
    for group in MODEL_GROUPS:
        provider, model = _current_group_choice(user_settings, group)
        lines.append(
            f"{group.title}: <b>{_provider_title(provider)}</b> → <code>{model}</code>"
        )
        lines.append(f"<i>{group.description}</i>")
        lines.append("")
    if include_policy_text:
        lines.append(include_policy_text)
        lines.append("")
    lines.append(f"Розширені налаштування і журнал транзакцій: {_TEXT_ONLY_SETTINGS_LINK}")
    return "\n".join(lines).strip()


def _settings_policy_text(policy: dict | None) -> str:
    if not policy:
        return "Доступ до чату: політика ще не ініціалізована."
    access_mode = (policy.get("access_mode") or "open").strip()
    per_user = _format_money(policy.get("per_user_daily_cap_uah"))
    per_chat = _format_money(policy.get("per_chat_daily_cap_uah"))
    return (
        "<b>Політика чату</b>\n"
        f"Режим: <code>{access_mode}</code>\n"
        f"Ліміт на юзера / день: <b>{per_user} грн</b>\n"
        f"Ліміт на чат / день: <b>{per_chat} грн</b>\n"
        "Змінюється owner-командами: /mode, /allow, /ban, /cap."
    )


def _button(text: str, callback_data: str) -> Any:
    if InlineKeyboardButton is None:
        return None
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def _model_root_markup(user_settings: dict[str, str]) -> Any | None:
    if InlineKeyboardMarkup is None:
        return None
    rows: list[list[Any]] = []
    for group in MODEL_GROUPS:
        _, model = _current_group_choice(user_settings, group)
        rows.append([_button(f"{group.title} · {model}", f"{_MODEL_CALLBACK_PREFIX}:group:{group.slug}")])
    return InlineKeyboardMarkup(rows)


def _settings_root_text(
    user_settings: dict[str, str],
    *,
    include_policy_text: str | None = None,
    headline: str = "💬 Налаштування",
    status_line: str | None = None,
) -> str:
    lines = [f"⚙️ <b>{headline}</b>"]
    if status_line:
        lines.append(status_line)
    lines.append(
        "Це персональні налаштування: вони впливають на те, якою моделлю, persona і голосом "
        "бот працює саме для тебе, не змінюючи інших людей у чаті."
    )
    lines.append("")
    for group in MODEL_GROUPS:
        provider, model = _current_group_choice(user_settings, group)
        lines.append(f"{group.title}: <b>{_provider_title(provider)}</b> → <code>{model}</code>")
        lines.append(f"<i>{group.description}</i>")
        lines.append("")
    current_voice = voice_option(_current_voice_choice(user_settings))
    if current_voice is not None:
        lines.append(f"🎙 Голос: <b>{current_voice.title}</b> → <code>{current_voice.voice_id}</code>")
        lines.append(f"<i>{current_voice.description}</i>")
        lines.append("")
    current_persona = persona_preset(_current_persona_choice(user_settings))
    if current_persona is not None:
        lines.append(f"🎭 Persona: <b>{current_persona.title}</b>")
        lines.append(f"<i>{current_persona.description}</i>")
        lines.append("")
    if include_policy_text:
        lines.append(include_policy_text)
        lines.append("")
    lines.append(f"Розширені налаштування і журнал транзакцій: {_TEXT_ONLY_SETTINGS_LINK}")
    return "\n".join(lines).strip()


def _settings_root_markup(user_settings: dict[str, str]) -> Any | None:
    if InlineKeyboardMarkup is None:
        return None
    rows: list[list[Any]] = []
    for group in MODEL_GROUPS:
        _, model = _current_group_choice(user_settings, group)
        rows.append([_button(f"{group.title} · {model}", f"{_MODEL_CALLBACK_PREFIX}:group:{group.slug}")])
    current_voice = voice_option(_current_voice_choice(user_settings))
    if current_voice is not None:
        rows.append([_button(f"🎙 Голос · {current_voice.title}", f"{_MODEL_CALLBACK_PREFIX}:voice")])
    current_persona = persona_preset(_current_persona_choice(user_settings))
    if current_persona is not None:
        rows.append([_button(f"🎭 Persona · {current_persona.title}", f"{_MODEL_CALLBACK_PREFIX}:persona")])
    return InlineKeyboardMarkup(rows)


def _voice_menu_text(user_settings: dict[str, str]) -> str:
    current = voice_option(_current_voice_choice(user_settings))
    lines = ["🎙 Голос озвучки", ""]
    if current is not None:
        lines.append(f"Поточний вибір: <b>{current.title}</b> → <code>{current.voice_id}</code>")
        lines.append(f"<i>{current.description}</i>")
        lines.append("")
    lines.append("Доступні голоси:")
    for option in VOICE_OPTIONS:
        marker = "✅" if current and option.voice_id == current.voice_id else "•"
        lines.append(f"{marker} <code>{option.voice_id}</code> — {option.title}")
    return "\n".join(lines)


def _voice_menu_markup(user_settings: dict[str, str]) -> Any | None:
    if InlineKeyboardMarkup is None:
        return None
    current = _current_voice_choice(user_settings)
    rows: list[list[Any]] = []
    for option in VOICE_OPTIONS:
        marker = "✅ " if option.voice_id == current else ""
        rows.append([_button(f"{marker}{option.title}", f"{_MODEL_CALLBACK_PREFIX}:voice_select:{option.voice_id}")])
    rows.append([
        _button("↩️ Назад", f"{_MODEL_CALLBACK_PREFIX}:root"),
        _button("Скинути", f"{_MODEL_CALLBACK_PREFIX}:voice_reset"),
    ])
    return InlineKeyboardMarkup(rows)


def _persona_menu_text(user_settings: dict[str, str]) -> str:
    current = persona_preset(_current_persona_choice(user_settings))
    lines = ["🎭 Persona", ""]
    if current is not None:
        lines.append(f"Поточний вибір: <b>{current.title}</b>")
        lines.append(f"<i>{current.description}</i>")
        lines.append("")
    lines.append("Доступні persona:")
    for option in PERSONA_PRESETS:
        marker = "✅" if current and option.slug == current.slug else "•"
        lines.append(f"{marker} <code>{option.slug}</code> — {option.title}")
    return "\n".join(lines)


def _persona_menu_markup(user_settings: dict[str, str]) -> Any | None:
    if InlineKeyboardMarkup is None:
        return None
    current = _current_persona_choice(user_settings)
    rows: list[list[Any]] = []
    for option in PERSONA_PRESETS:
        marker = "✅ " if option.slug == current else ""
        rows.append([_button(f"{marker}{option.title}", f"{_MODEL_CALLBACK_PREFIX}:persona_select:{option.slug}")])
    rows.append([
        _button("↩️ Назад", f"{_MODEL_CALLBACK_PREFIX}:root"),
        _button("Скинути", f"{_MODEL_CALLBACK_PREFIX}:persona_reset"),
    ])
    return InlineKeyboardMarkup(rows)


def _group_markup(
    group: ModelGroupDef,
    available_providers: list[str],
    user_settings: dict[str, str],
) -> Any | None:
    if InlineKeyboardMarkup is None:
        return None
    current_provider, _ = _current_group_choice(user_settings, group)
    rows: list[list[Any]] = []
    for provider in available_providers:
        marker = "✅ " if provider == current_provider else ""
        rows.append([
            _button(
                f"{marker}{_provider_title(provider)}",
                f"{_MODEL_CALLBACK_PREFIX}:provider:{group.slug}:{provider}",
            )
        ])
    rows.append([
        _button("↩️ Назад", f"{_MODEL_CALLBACK_PREFIX}:root"),
        _button("Скинути", f"{_MODEL_CALLBACK_PREFIX}:reset:{group.slug}"),
    ])
    return InlineKeyboardMarkup(rows)


def _group_text(
    group: ModelGroupDef,
    available_providers: list[str],
    user_settings: dict[str, str],
) -> str:
    current_provider, current_model = _current_group_choice(user_settings, group)
    lines = [f"{group.title}", group.description, ""]
    lines.append(f"Поточний вибір: <b>{_provider_title(current_provider)}</b> → <code>{current_model}</code>")
    lines.append("")
    if not available_providers:
        lines.append("Немає жодного провайдера з API-ключем для цієї групи.")
        return "\n".join(lines)
    lines.append("Доступні провайдери:")
    for provider in available_providers:
        marker = "•"
        if provider == current_provider:
            marker = "✅"
        lines.append(f"{marker} {_provider_title(provider)}")
    return "\n".join(lines)


def _provider_markup(
    group: ModelGroupDef,
    provider_slug: str,
    user_settings: dict[str, str],
) -> Any | None:
    if InlineKeyboardMarkup is None:
        return None
    _, current_model = _current_group_choice(user_settings, group)
    rows: list[list[Any]] = []
    for model in group.providers.get(provider_slug, tuple()):
        marker = "✅ " if model == current_model else ""
        rows.append([
            _button(
                f"{marker}{model}",
                f"{_MODEL_CALLBACK_PREFIX}:select:{group.slug}:{provider_slug}:{model}",
            )
        ])
    rows.append([
        _button("↩️ До провайдерів", f"{_MODEL_CALLBACK_PREFIX}:group:{group.slug}"),
        _button("До груп", f"{_MODEL_CALLBACK_PREFIX}:root"),
    ])
    return InlineKeyboardMarkup(rows)


def _provider_text(
    group: ModelGroupDef,
    provider_slug: str,
    user_settings: dict[str, str],
) -> str:
    current_provider, current_model = _current_group_choice(user_settings, group)
    lines = [f"{group.title} → {_provider_title(provider_slug)}", ""]
    for model in group.providers.get(provider_slug, tuple()):
        marker = "✅" if provider_slug == current_provider and model == current_model else "•"
        lines.append(f"{marker} <code>{model}</code>")
    return "\n".join(lines)


async def _render_model_root(
    *,
    user_id: int,
    include_policy_text: str | None = None,
    status_line: str | None = None,
    headline: str = "Персональний вибір моделей",
) -> tuple[str, Any | None]:
    user_settings = await get_user_settings(user_id)
    return (
        _settings_root_text(
            user_settings,
            include_policy_text=include_policy_text,
            status_line=status_line,
            headline=headline,
        ),
        _settings_root_markup(user_settings),
    )


async def _render_group_menu(user_id: int, group_slug: str) -> tuple[str, Any | None]:
    group = group_by_slug(group_slug)
    if group is None:
        return "Невідома група налаштувань.", None
    user_settings = await get_user_settings(user_id)
    available_providers = await _available_providers_for_group(group)
    return (
        _group_text(group, available_providers, user_settings),
        _group_markup(group, available_providers, user_settings),
    )


async def _render_provider_menu(
    user_id: int,
    group_slug: str,
    provider_slug: str,
) -> tuple[str, Any | None]:
    group = group_by_slug(group_slug)
    if group is None:
        return "Невідома група налаштувань.", None
    if provider_slug not in group.providers:
        return "Невідомий провайдер для цієї групи.", None
    if not await _provider_available(provider_slug):
        return "Для цього провайдера зараз немає доступного API-ключа.", None
    user_settings = await get_user_settings(user_id)
    return (
        _provider_text(group, provider_slug, user_settings),
        _provider_markup(group, provider_slug, user_settings),
    )


async def _set_group_choice(
    *,
    user_id: int,
    group_slug: str,
    provider_slug: str | None,
    model_name: str | None,
) -> tuple[str, Any | None]:
    group = group_by_slug(group_slug)
    if group is None:
        return "Невідома група налаштувань.", None
    if provider_slug is None:
        await set_user_setting(user_id, group.provider_setting_key, None)
        await set_user_setting(user_id, group.model_setting_key, None)
        return await _render_model_root(
            user_id=user_id,
            status_line=f"Скинуто персональний вибір для групи {group.title}. Тепер використовується server default.",
        )
    allowed_models = group.providers.get(provider_slug, tuple())
    if provider_slug not in group.providers or model_name not in allowed_models:
        return "Невалідна комбінація провайдера і моделі.", None
    if not await _provider_available(provider_slug):
        return "Для цього провайдера зараз немає доступного API-ключа.", None
    await set_user_setting(user_id, group.provider_setting_key, provider_slug)
    await set_user_setting(user_id, group.model_setting_key, model_name)
    return await _render_model_root(
        user_id=user_id,
        status_line=(
            f"Збережено для {group.title}: <b>{_provider_title(provider_slug)}</b> → "
            f"<code>{model_name}</code>."
        ),
    )


async def _render_voice_menu(user_id: int) -> tuple[str, Any | None]:
    user_settings = await get_user_settings(user_id)
    return _voice_menu_text(user_settings), _voice_menu_markup(user_settings)


async def _render_persona_menu(user_id: int) -> tuple[str, Any | None]:
    user_settings = await get_user_settings(user_id)
    return _persona_menu_text(user_settings), _persona_menu_markup(user_settings)


async def _set_voice_choice(user_id: int, voice_id: str | None) -> tuple[str, Any | None]:
    if voice_id is None:
        await set_user_setting(user_id, "voice_id", None)
        return await _render_model_root(
            user_id=user_id,
            status_line="Скинуто персональний голос озвучки. Тепер використовується server default.",
        )
    option = voice_option(voice_id)
    if option is None:
        return "Невідомий voice id.", None
    await set_user_setting(user_id, "voice_id", option.voice_id)
    return await _render_model_root(
        user_id=user_id,
        status_line=f"Збережено голос озвучки: <b>{option.title}</b> → <code>{option.voice_id}</code>.",
    )


async def _set_persona_choice(user_id: int, persona_slug: str | None) -> tuple[str, Any | None]:
    if persona_slug is None:
        await set_user_setting(user_id, "persona_slug", None)
        return await _render_model_root(
            user_id=user_id,
            status_line="Скинуто персональний persona override. Тепер використовується server default.",
        )
    preset = persona_preset(persona_slug)
    if preset is None:
        return "Невідома persona.", None
    await set_user_setting(user_id, "persona_slug", preset.slug)
    return await _render_model_root(
        user_id=user_id,
        status_line=f"Збережено persona: <b>{preset.title}</b>.",
    )


async def _handle_model_callback(update: Update, bot_username: str | None) -> bool:
    callback = getattr(update, "callback_query", None)
    if callback is None:
        return False
    data = str(getattr(callback, "data", "") or "").strip()
    if not data.startswith(f"{_MODEL_CALLBACK_PREFIX}:"):
        return False

    user = getattr(callback, "from_user", None)
    user_id = getattr(user, "id", None)
    if not user_id:
        await callback.answer("Не вдалося визначити користувача.", show_alert=True)
        return True

    _, _, action_payload = data.partition(":")
    parts = action_payload.split(":")
    action = parts[0] if parts else ""

    try:
        if action == "root":
            text, markup = await _render_model_root(user_id=int(user_id))
        elif action == "voice":
            text, markup = await _render_voice_menu(int(user_id))
        elif action == "persona":
            text, markup = await _render_persona_menu(int(user_id))
        elif action == "group" and len(parts) >= 2:
            text, markup = await _render_group_menu(int(user_id), parts[1])
        elif action == "provider" and len(parts) >= 3:
            text, markup = await _render_provider_menu(int(user_id), parts[1], parts[2])
        elif action == "select" and len(parts) >= 4:
            group_slug = parts[1]
            provider_slug = parts[2]
            model_name = ":".join(parts[3:])
            text, markup = await _set_group_choice(
                user_id=int(user_id),
                group_slug=group_slug,
                provider_slug=provider_slug,
                model_name=model_name,
            )
        elif action == "reset" and len(parts) >= 2:
            text, markup = await _set_group_choice(
                user_id=int(user_id),
                group_slug=parts[1],
                provider_slug=None,
                model_name=None,
            )
        elif action == "voice_select" and len(parts) >= 2:
            text, markup = await _set_voice_choice(int(user_id), parts[1])
        elif action == "voice_reset":
            text, markup = await _set_voice_choice(int(user_id), None)
        elif action == "persona_select" and len(parts) >= 2:
            text, markup = await _set_persona_choice(int(user_id), parts[1])
        elif action == "persona_reset":
            text, markup = await _set_persona_choice(int(user_id), None)
        else:
            text, markup = "Невідома дія меню моделей.", None
    except Exception as exc:
        logger.exception("billing.commands.callback_failed action=%s error=%s", action, exc)
        await callback.answer("Не вдалося оновити налаштування.", show_alert=True)
        return True

    await callback.answer()
    if getattr(callback, "message", None) is not None:
        await callback.edit_message_text(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=markup,
        )
    return True


async def _require_chat_owner(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
) -> tuple[dict | None, dict | None, CommandResult | None]:
    if geometry.chat_type == "private":
        return None, None, CommandResult(
            handled=True,
            response_text="Ця команда має сенс тільки в груповому чаті, де є owner і політика доступу.",
            capability="command_owner_gate",
        )
    user_id = getattr(geometry.sender, "user_id", None)
    if not user_id:
        return None, None, CommandResult(
            handled=True,
            response_text="Не вдалося визначити Telegram user_id відправника.",
            capability="command_owner_gate",
            finalize_status="failed",
        )
    account = await get_account_by_owner(int(user_id))
    if not account:
        return None, None, CommandResult(
            handled=True,
            response_text="У тебе ще немає billing-акаунта. Почни з /start у приватці.",
            capability="command_owner_gate",
        )
    chat = await get_chat(int(msg.chat_id))
    if not chat or not chat.get("owner_account_id"):
        return None, None, CommandResult(
            handled=True,
            response_text="Для цього чату ще не призначено owner-акаунт.",
            capability="command_owner_gate",
        )
    if int(chat["owner_account_id"]) != int(account["account_id"]):
        return account, chat, CommandResult(
            handled=True,
            response_text="Цю дію може виконувати тільки власник чату.",
            capability="command_owner_gate",
        )
    return account, chat, None


def _resolve_username_arg(args: str) -> str:
    return (args or "").strip().split()[0].lstrip("@")


async def _cmd_start(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del args, billing_ctx
    if geometry.chat_type != "private":
        return CommandResult(
            handled=True,
            response_text=(
                "Ця команда потрібна в приватному чаті з ботом. "
                "Напиши мені в приватному, щоб створити акаунт і побачити баланс."
            ),
            capability="command_start",
        )

    user_id = getattr(geometry.sender, "user_id", None)
    if not user_id:
        return CommandResult(True, "Не вдалося визначити твій Telegram user_id.", "command_start", finalize_status="failed")

    await upsert_user(
        int(user_id),
        tg_username=getattr(geometry.sender, "username", None),
        first_name=getattr(geometry.sender, "display_name", None),
    )
    account = await get_account_by_owner(int(user_id))
    if not account:
        account_id = await create_account(int(user_id), initial_balance_uah=0)
        account = await get_account(account_id)
        return CommandResult(
            handled=True,
            response_text=(
                "Створив тобі billing-акаунт.\n"
                f"Баланс: <b>{_format_money(account['balance_uah'] if account else 0)} грн</b>\n\n"
                "Далі можеш дивитися /balance, налаштовувати /settings і поповнювати /topup."
            ),
            capability="command_start",
        )

    return CommandResult(
        handled=True,
        response_text=(
            "Акаунт уже існує.\n"
            f"Баланс: <b>{_format_money(account.get('balance_uah'))} грн</b>\n\n"
            "Команди: /balance, /settings, /topup."
        ),
        capability="command_start",
    )


async def _cmd_balance(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del billing_ctx
    user_id = getattr(geometry.sender, "user_id", None)
    if not user_id:
        return CommandResult(True, "Не вдалося визначити твій Telegram user_id.", "command_balance", finalize_status="failed")
    account = await get_account_by_owner(int(user_id))
    if not account:
        return CommandResult(
            handled=True,
            response_text="У тебе ще немає акаунта. Спочатку напиши /start у приватному чаті з ботом.",
            capability="command_balance",
        )

    chat_today = Decimal("0")
    if geometry.chat_type != "private":
        chat_today = await sum_chat_spent_today(int(msg.chat_id))
    account_id = int(account["account_id"])
    normalized_args = (args or "").strip()
    lowered_args = normalized_args.lower()

    if lowered_args == "last":
        turn = await get_latest_turn_for_account(account_id)
        if not turn:
            return CommandResult(True, "У тебе ще немає turn-ів із витратами.", "command_balance")
        transactions = await get_transactions_for_turn(str(turn["turn_id"]))
        return CommandResult(True, _render_turn_breakdown(turn, transactions), "command_balance")

    if lowered_args.startswith("turn "):
        turn_ref = normalized_args[5:].strip()
        turn, error_text = await _resolve_turn_for_balance(account_id, turn_ref)
        if error_text:
            return CommandResult(True, error_text, "command_balance")
        assert turn is not None
        transactions = await get_transactions_for_turn(str(turn["turn_id"]))
        return CommandResult(True, _render_turn_breakdown(turn, transactions), "command_balance")

    if normalized_args:
        return CommandResult(
            True,
            "Формат: <code>/balance</code>, <code>/balance last</code> або <code>/balance turn &lt;id&gt;</code>.",
            "command_balance",
        )

    turns = await list_turns_for_account(account_id, limit=5)

    lines = [
        "💳 <b>Баланс</b>",
        f"Поточний баланс: <b>{_format_money(account.get('balance_uah'))} грн</b>",
        f"Поповнено всього: <b>{_format_money(account.get('total_topup_uah'))} грн</b>",
        f"Витрачено всього: <b>{_format_money(account.get('total_spent_uah'))} грн</b>",
    ]
    if geometry.chat_type != "private":
        lines.append(f"Витрати цього чату сьогодні: <b>{_format_money(chat_today)} грн</b>")
    if turns:
        lines.append("")
        lines.append("Останні turn-и:")
        for row in turns[:5]:
            capability = (row.get("capability") or "unknown").strip()
            total = _format_money(row.get("total_cost_uah"))
            status = _turn_status_label(row.get("status"))
            turn_id = str(row.get("turn_id") or "")
            short_id = _short_turn_id(turn_id, size=12)
            lines.append(f"• <code>{short_id}</code> — {capability} — {total} грн — {status}")
            lines.append(f"  Деталі: <code>/balance turn {short_id}</code>")
    lines.append("")
    lines.append("Деталі по останньому turn-у: <code>/balance last</code>")
    lines.append("Деталі по конкретному turn-у: <code>/balance turn &lt;id&gt;</code>")
    return CommandResult(True, "\n".join(lines), "command_balance")


async def _cmd_topup(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del msg, billing_ctx
    amount = _parse_amount(args)
    if amount is None:
        return CommandResult(
            True,
            "Формат: <code>/topup 100</code>. Сума має бути додатною і в гривнях.",
            "command_topup",
        )
    if amount < _MIN_TOPUP_UAH:
        return CommandResult(
            True,
            f"Мінімальне поповнення зараз <b>{_format_money(_MIN_TOPUP_UAH)} грн</b>.",
            "command_topup",
        )

    user_id = getattr(geometry.sender, "user_id", None)
    if not user_id:
        return CommandResult(True, "Не вдалося визначити твій Telegram user_id.", "command_topup", finalize_status="failed")
    account = await get_account_by_owner(int(user_id))
    if not account:
        return CommandResult(
            True,
            "У тебе ще немає акаунта. Почни з /start у приватці.",
            "command_topup",
        )

    await create_topup(
        account_id=int(account["account_id"]),
        amount_uah=amount,
        status="created",
        note="stage5_pending",
    )
    return CommandResult(
        True,
        (
            f"Створив запит на поповнення <b>{_format_money(amount)} грн</b>.\n\n"
            "Автоматичний еквайринг ще не ввімкнений — це приїде на Етапу 5. "
            "Поки що поповнення підтверджує адмін вручну."
        ),
        "command_topup",
    )


async def _cmd_mode(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del billing_ctx
    _, _, error = await _require_chat_owner(msg, geometry)
    if error:
        return error
    access_mode = (args or "").strip().lower()
    if access_mode not in {"open", "whitelist", "admins_only", "owner_only"}:
        return CommandResult(
            True,
            "Формат: <code>/mode open|whitelist|admins_only|owner_only</code>",
            "command_mode",
        )
    await update_chat_policy(int(msg.chat_id), access_mode=access_mode)
    return CommandResult(
        True,
        f"Оновив режим доступу для цього чату: <code>{access_mode}</code>.",
        "command_mode",
    )


async def _resolve_target_user(username_arg: str) -> dict | None:
    username = _resolve_username_arg(username_arg)
    if not username:
        return None
    return await get_user_by_username(username)


async def _cmd_allow(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del billing_ctx
    _, _, error = await _require_chat_owner(msg, geometry)
    if error:
        return error
    user = await _resolve_target_user(args)
    username = _resolve_username_arg(args)
    if not user:
        return CommandResult(
            True,
            f"Не знайшов користувача <code>@{username}</code> серед відомих юзерів бота.",
            "command_allow",
        )
    await upsert_chat_access(int(msg.chat_id), int(user["user_id"]), "allowed", added_by=getattr(geometry.sender, "user_id", None))
    return CommandResult(
        True,
        f"Додав користувача <code>{user['user_id']}</code> у whitelist цього чату.",
        "command_allow",
    )


async def _cmd_ban(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del billing_ctx
    _, _, error = await _require_chat_owner(msg, geometry)
    if error:
        return error
    user = await _resolve_target_user(args)
    username = _resolve_username_arg(args)
    if not user:
        return CommandResult(
            True,
            f"Не знайшов користувача <code>@{username}</code> серед відомих юзерів бота.",
            "command_ban",
        )
    await upsert_chat_access(int(msg.chat_id), int(user["user_id"]), "banned", added_by=getattr(geometry.sender, "user_id", None))
    return CommandResult(True, f"Забанив <code>@{username}</code> у межах цього чату.", "command_ban")


async def _cmd_unban(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del billing_ctx
    _, _, error = await _require_chat_owner(msg, geometry)
    if error:
        return error
    user = await _resolve_target_user(args)
    username = _resolve_username_arg(args)
    if not user:
        return CommandResult(
            True,
            f"Не знайшов користувача <code>@{username}</code> серед відомих юзерів бота.",
            "command_unban",
        )
    await remove_chat_access(int(msg.chat_id), int(user["user_id"]))
    return CommandResult(True, f"Прибрав обмеження для <code>@{username}</code>.", "command_unban")


async def _cmd_cap(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del billing_ctx
    _, _, error = await _require_chat_owner(msg, geometry)
    if error:
        return error
    scope, _, value = (args or "").strip().partition(" ")
    amount = _parse_amount(value)
    if scope not in {"user", "chat"} or amount is None:
        return CommandResult(
            True,
            "Формат: <code>/cap user 10</code> або <code>/cap chat 100</code>.",
            "command_cap",
        )
    if scope == "user":
        await update_chat_policy(int(msg.chat_id), per_user_daily_cap_uah=amount)
        return CommandResult(True, f"Ліміт на одного користувача оновлено: <b>{_format_money(amount)} грн/день</b>.", "command_cap")
    await update_chat_policy(int(msg.chat_id), per_chat_daily_cap_uah=amount)
    return CommandResult(True, f"Ліміт на чат оновлено: <b>{_format_money(amount)} грн/день</b>.", "command_cap")


async def _cmd_model(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del args, billing_ctx
    user_id = getattr(geometry.sender, "user_id", None)
    if not user_id:
        return CommandResult(True, "Не вдалося визначити твій Telegram user_id.", "command_model", finalize_status="failed")
    if _supports_inline(msg):
        text, markup = await _render_model_root(user_id=int(user_id))
        return CommandResult(
            handled=True,
            response_text=text,
            capability="command_model",
            response_markup=markup,
        )
    text, _ = await _render_model_root(user_id=int(user_id))
    text = (
        f"{text}\n\n"
        "У цьому клієнті inline-клавіатури недоступні. "
        f"Для повного контролю використовуй {_TEXT_ONLY_SETTINGS_LINK}."
    )
    return CommandResult(True, text, "command_model")


async def _cmd_settings(
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    args: str,
    billing_ctx: BillingContext | None,
) -> CommandResult:
    del args, billing_ctx
    user_id = getattr(geometry.sender, "user_id", None)
    if not user_id:
        return CommandResult(True, "Не вдалося визначити твій Telegram user_id.", "command_settings", finalize_status="failed")

    include_policy_text: str | None = None
    if geometry.chat_type != "private":
        policy = await ensure_chat_policy(int(msg.chat_id))
        include_policy_text = _settings_policy_text(policy)
    if _supports_inline(msg):
        text, markup = await _render_model_root(
            user_id=int(user_id),
            include_policy_text=include_policy_text,
            headline="Налаштування",
        )
        return CommandResult(
            handled=True,
            response_text=text,
            capability="command_settings",
            response_markup=markup,
        )
    text, _ = await _render_model_root(
        user_id=int(user_id),
        include_policy_text=include_policy_text,
        headline="Налаштування",
    )
    text = (
        f"{text}\n\n"
        "Inline-клавіатури тут недоступні. "
        f"Для web-порталу і детальніших налаштувань використовуй {_TEXT_ONLY_SETTINGS_LINK}."
    )
    return CommandResult(True, text, "command_settings")


_COMMAND_HANDLERS: dict[str, CommandHandler] = {
    "/start": _cmd_start,
    "/balance": _cmd_balance,
    "/topup": _cmd_topup,
    "/mode": _cmd_mode,
    "/allow": _cmd_allow,
    "/ban": _cmd_ban,
    "/unban": _cmd_unban,
    "/cap": _cmd_cap,
    "/settings": _cmd_settings,
    "/model": _cmd_model,
}


async def try_handle_command(
    *,
    msg: UnifiedMessage,
    geometry: MessageGeometry,
    billing_ctx: BillingContext | None,
) -> CommandResult | None:
    parsed = parse_command(msg.text or msg.caption, msg.bot_username)
    if parsed is None:
        return None
    command, args = parsed
    handler = _COMMAND_HANDLERS[command]
    try:
        return await handler(msg, geometry, args, billing_ctx)
    except Exception as exc:
        logger.exception("billing.commands.dispatch_failed command=%s error=%s", command, exc)
        return CommandResult(
            handled=True,
            response_text="Команда зламалась під час виконання. Подивлюся лог і виправлю.",
            capability=f"command_{command.lstrip('/')}",
            finalize_status="failed",
        )


async def try_handle_callback(update: Update, bot_username: str | None = None) -> bool:
    callback = getattr(update, "callback_query", None)
    if callback is None:
        return False
    data = str(getattr(callback, "data", "") or "").strip()
    if not data.startswith(f"{_MODEL_CALLBACK_PREFIX}:"):
        return False
    return await _handle_model_callback(update, bot_username)
