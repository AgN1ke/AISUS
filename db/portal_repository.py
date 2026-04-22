from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from core.env import provider_api_key
from core.model_preferences import MODEL_GROUPS
from core.user_preferences import PERSONA_PRESETS, VOICE_OPTIONS, persona_preset, voice_option

from .accounts_repository import create_account, get_account, get_account_by_owner
from .keypool_repository import list_provider_keys
from .topups_repository import create_topup, get_topup, list_topups_for_account
from .transactions_repository import (
    find_turns_for_account,
    get_transactions_for_turn,
    get_turn,
    list_turns_for_account,
)
from .users_repository import get_user, get_user_settings, set_user_setting, upsert_user

_PROVIDER_TITLES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Gemini",
    "deepseek": "DeepSeek",
    "mistral": "Mistral",
    "xai": "xAI",
}


def _provider_title(provider_slug: str) -> str:
    normalized = (provider_slug or "").strip().lower()
    return _PROVIDER_TITLES.get(normalized, normalized or "Provider")


def _model_choice_value(provider_slug: str | None, model_name: str | None) -> str:
    provider = (provider_slug or "").strip().lower()
    model = (model_name or "").strip()
    if not provider or not model:
        return ""
    return f"{provider}::{model}"


def _split_model_choice(raw_value: str | None) -> tuple[str | None, str | None]:
    raw = (raw_value or "").strip()
    if not raw or "::" not in raw:
        return None, None
    provider_slug, model_name = raw.split("::", 1)
    provider = provider_slug.strip().lower()
    model = model_name.strip()
    if not provider or not model:
        return None, None
    return provider, model


async def _provider_available(provider_slug: str) -> bool:
    if provider_api_key(provider_slug):
        return True
    try:
        rows = await list_provider_keys(provider_slug)
    except Exception:
        return False
    return any((row.get("status") or "").strip().lower() in {"active", "disabled", "rate_limited"} for row in rows)


async def _settings_catalog(settings: dict[str, str]) -> dict:
    groups: list[dict] = []
    for group in MODEL_GROUPS:
        choices = [{"value": "", "label": "Server default"}]
        for provider_slug, model_names in group.providers.items():
            if not await _provider_available(provider_slug):
                continue
            provider_title = _provider_title(provider_slug)
            for model_name in model_names:
                choices.append(
                    {
                        "value": _model_choice_value(provider_slug, model_name),
                        "label": f"{provider_title} — {model_name}",
                    }
                )
        groups.append(
            {
                "slug": group.slug,
                "title": group.title,
                "description": group.description,
                "field_name": f"model_group_{group.slug}",
                "current_value": _model_choice_value(
                    settings.get(group.provider_setting_key),
                    settings.get(group.model_setting_key),
                ),
                "choices": choices,
            }
        )

    voices = {
        "field_name": "voice_id",
        "current_value": (settings.get("voice_id") or "").strip().lower(),
        "choices": [{"value": "", "label": "Server default"}]
        + [
            {
                "value": option.voice_id,
                "label": f"{option.title} — {option.description}",
            }
            for option in VOICE_OPTIONS
        ],
    }
    personas = {
        "field_name": "persona_slug",
        "current_value": (settings.get("persona_slug") or "").strip().lower(),
        "choices": [{"value": "", "label": "Server default"}]
        + [
            {
                "value": preset.slug,
                "label": f"{preset.title} — {preset.description}",
            }
            for preset in PERSONA_PRESETS
            if preset.slug != "default"
        ],
    }
    return {
        "groups": groups,
        "voices": voices,
        "personas": personas,
    }


async def ensure_portal_identity(
    *,
    user_id: int,
    tg_username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    lang_code: str | None = None,
    phone_number: str | None = None,
) -> dict:
    await upsert_user(
        user_id=user_id,
        tg_username=tg_username,
        first_name=first_name,
        last_name=last_name,
        lang_code=lang_code,
    )
    if phone_number:
        await set_user_setting(user_id, "profile_phone_number", phone_number)
    user = await get_user(user_id)
    account = await get_account_by_owner(user_id)
    if account is None:
        account_id = await create_account(owner_user_id=user_id)
        account = await get_account(account_id)
    settings = await get_user_settings(user_id)
    return {
        "user": user,
        "account": account,
        "settings": settings,
    }


async def get_portal_dashboard(
    user_id: int,
    *,
    turn_limit: int = 12,
) -> Optional[dict]:
    user = await get_user(user_id)
    account = await get_account_by_owner(user_id)
    if not user or not account:
        return None
    turns = await list_turns_for_account(account["account_id"], limit=turn_limit)
    settings = await get_user_settings(user_id)
    return {
        "user": user,
        "account": account,
        "turns": turns,
        "settings": settings,
    }


async def get_portal_history(
    user_id: int,
    *,
    limit: int = 50,
) -> Optional[dict]:
    user = await get_user(user_id)
    account = await get_account_by_owner(user_id)
    if not user or not account:
        return None
    turns = await list_turns_for_account(account["account_id"], limit=limit)
    return {
        "user": user,
        "account": account,
        "turns": turns,
    }


async def get_portal_turn_detail(
    user_id: int,
    turn_ref: str,
) -> Optional[dict]:
    account = await get_account_by_owner(user_id)
    user = await get_user(user_id)
    if not user or not account:
        return None
    ref = (turn_ref or "").strip()
    if not ref:
        return None

    turn = None
    ambiguous_matches: list[dict] = []
    if len(ref) >= 32 and "-" in ref:
        candidate = await get_turn(ref)
        if candidate and int(candidate.get("account_id") or 0) == int(account["account_id"]):
            turn = candidate
    if turn is None:
        matches = await find_turns_for_account(account["account_id"], ref, limit=5)
        if len(matches) == 1:
            turn = matches[0]
        elif len(matches) > 1:
            ambiguous_matches = matches
    if turn is None:
        return {
            "user": user,
            "account": account,
            "turn": None,
            "transactions": [],
            "ambiguous_matches": ambiguous_matches,
        }

    transactions = await get_transactions_for_turn(turn["turn_id"])
    return {
        "user": user,
        "account": account,
        "turn": turn,
        "transactions": transactions,
        "ambiguous_matches": [],
    }


async def get_portal_settings(user_id: int) -> Optional[dict]:
    user = await get_user(user_id)
    account = await get_account_by_owner(user_id)
    if not user or not account:
        return None
    settings = await get_user_settings(user_id)
    return {
        "user": user,
        "account": account,
        "settings": settings,
        "catalog": await _settings_catalog(settings),
    }


async def update_portal_settings(
    user_id: int,
    *,
    model_choices: dict[str, str] | None = None,
    voice_id: str | None = None,
    persona_slug: str | None = None,
) -> dict[str, str]:
    model_choices = model_choices or {}

    for group in MODEL_GROUPS:
        raw_choice = model_choices.get(group.slug, "")
        provider_slug, model_name = _split_model_choice(raw_choice)
        if provider_slug is None or model_name is None:
            await set_user_setting(user_id, group.provider_setting_key, None)
            await set_user_setting(user_id, group.model_setting_key, None)
            continue
        allowed_models = group.providers.get(provider_slug, tuple())
        if model_name not in allowed_models:
            raise ValueError(f"Невалідний вибір моделі для групи {group.title}.")
        if not await _provider_available(provider_slug):
            raise ValueError(f"Для {_provider_title(provider_slug)} зараз немає доступного API-ключа.")
        await set_user_setting(user_id, group.provider_setting_key, provider_slug)
        await set_user_setting(user_id, group.model_setting_key, model_name)

    normalized_voice = (voice_id or "").strip().lower()
    if not normalized_voice:
        await set_user_setting(user_id, "voice_id", None)
    else:
        option = voice_option(normalized_voice)
        if option is None:
            raise ValueError("Невідомий голос озвучки.")
        await set_user_setting(user_id, "voice_id", option.voice_id)

    normalized_persona = (persona_slug or "").strip().lower()
    if not normalized_persona or normalized_persona == "default":
        await set_user_setting(user_id, "persona_slug", None)
    else:
        preset = persona_preset(normalized_persona)
        if preset is None:
            raise ValueError("Невідома persona.")
        await set_user_setting(user_id, "persona_slug", preset.slug)

    return await get_user_settings(user_id)


async def get_portal_topups(
    user_id: int,
    *,
    limit: int = 20,
) -> Optional[dict]:
    user = await get_user(user_id)
    account = await get_account_by_owner(user_id)
    if not user or not account:
        return None
    topups = await list_topups_for_account(account["account_id"], limit=limit)
    return {
        "user": user,
        "account": account,
        "topups": topups,
    }


async def create_portal_topup_request(
    user_id: int,
    *,
    amount_uah: Decimal | str | int | float,
    note: str | None = None,
) -> dict:
    user = await get_user(user_id)
    account = await get_account_by_owner(user_id)
    if not user or not account:
        raise ValueError("Портал ще не готовий для цього користувача.")

    try:
        amount = Decimal(str(amount_uah)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("Сума поповнення має бути числом.") from None
    if amount <= 0:
        raise ValueError("Сума поповнення має бути більшою за нуль.")

    clean_note = " ".join((note or "").split())
    stored_note = "portal_request"
    if clean_note:
        stored_note = f"portal_request: {clean_note}"[:255]

    topup_id = await create_topup(
        account_id=int(account["account_id"]),
        amount_uah=amount,
        status="pending",
        note=stored_note,
    )
    topup = await get_topup(topup_id)
    return {
        "user": user,
        "account": account,
        "topup": topup,
    }
