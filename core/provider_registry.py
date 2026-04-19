from __future__ import annotations

import logging
from dataclasses import dataclass
import asyncio
import threading

import os

from core.model_preferences import group_for_capability
from core.runtime_user_settings import current_runtime_user_settings
from core.env import (
    capability_adapter,
    capability_model,
    capability_provider,
    provider_api_key,
    provider_base_url,
)

logger = logging.getLogger(__name__)


def _default_adapter_for_provider(provider_name: str, fallback: str) -> str:
    provider = (provider_name or "").strip().lower()
    if provider == "gemini":
        return "gemini_generate_content"
    return fallback


@dataclass(frozen=True)
class ProviderBinding:
    capability: str
    provider: str
    adapter: str
    model: str
    api_key: str
    base_url: str | None = None
    key_id: int | None = None
    key_label: str | None = None
    key_source: str = "env"
def _current_billing_context():
    try:
        from billing.runtime import current_billing_context
    except Exception:
        return None
    return current_billing_context()


def _current_billing_meta() -> dict | None:
    ctx = _current_billing_context()
    if ctx is None:
        return None
    meta = getattr(ctx, "meta", None)
    return meta if isinstance(meta, dict) else None


def _billing_turn_active() -> bool:
    ctx = _current_billing_context()
    return bool(ctx and getattr(ctx, "is_complete", lambda: False)())


def _run_async_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    holder: dict[str, object] = {}

    def runner() -> None:
        try:
            holder["result"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - surfaced to caller
            holder["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in holder:
        raise holder["error"]  # type: ignore[misc]
    return holder.get("result")


def _cached_keypool_binding(provider_name: str) -> tuple[str | None, int | None, str | None]:
    provider = (provider_name or "").strip().lower()
    if not provider:
        return None, None, None

    meta = _current_billing_meta()
    if meta is None:
        return None, None, None
    cache = meta.setdefault("_provider_key_cache", {}) if isinstance(meta, dict) else {}
    if isinstance(cache, dict):
        cached = cache.get(provider)
        if isinstance(cached, dict):
            return (
                str(cached.get("api_key") or "") or None,
                int(cached["key_id"]) if cached.get("key_id") else None,
                str(cached.get("label") or "") or None,
            )

    try:
        from billing.keypool import acquire
    except Exception:
        return None, None, None

    try:
        acquired = _run_async_sync(acquire(provider))
    except Exception:
        return None, None, None
    if not acquired:
        return None, None, None

    api_key = str(getattr(acquired, "api_key", "") or "") or None
    key_id = getattr(acquired, "key_id", None)
    label = str(getattr(acquired, "label", "") or "") or None
    if api_key and isinstance(cache, dict):
        cache[provider] = {
            "api_key": api_key,
            "key_id": key_id,
            "label": label,
        }
    return api_key, int(key_id) if key_id else None, label


def _warn_env_fallback_for_billed_turn(
    capability_name: str,
    provider_name: str,
    *,
    source: str,
) -> None:
    meta = _current_billing_meta()
    if meta is None:
        return
    warned = meta.setdefault("_provider_env_fallback_warned", set())
    if not isinstance(warned, set):
        warned = set()
        meta["_provider_env_fallback_warned"] = warned
    marker = (capability_name, provider_name, source)
    if marker in warned:
        return
    warned.add(marker)
    logger.warning(
        "provider_registry.env_fallback_used capability=%s provider=%s source=%s",
        capability_name,
        provider_name,
        source,
    )


def _settings_override_for_capability(
    capability_name: str,
) -> tuple[str | None, str | None]:
    group = group_for_capability(capability_name)
    if group is None:
        return None, None
    settings = current_runtime_user_settings()
    provider = (settings.get(group.provider_setting_key) or "").strip().lower() or None
    model = (settings.get(group.model_setting_key) or "").strip() or None
    allowed_models = group.providers.get(provider or "", tuple()) if provider else tuple()
    if provider and model and model not in allowed_models:
        model = None
    if provider and provider not in group.providers:
        provider = None
        model = None
    return provider, model


def resolve_provider_binding(
    capability_name: str,
    *,
    model: str | None = None,
    default_adapter: str = "openai_chat",
) -> ProviderBinding:
    capability = (capability_name or "chat_final").strip() or "chat_final"
    provider = capability_provider(capability)
    override_provider, override_model = _settings_override_for_capability(capability)
    if override_provider:
        provider = override_provider
    adapter_default = _default_adapter_for_provider(provider, default_adapter)
    resolved_model = (model or override_model or capability_model(capability)).strip()
    explicit_api_key = os.getenv(f"CAPABILITY_{capability.upper()}_API_KEY", "").strip()
    key_id: int | None = None
    key_label: str | None = None
    key_source = "env"
    resolved_api_key = ""
    billing_turn_active = _billing_turn_active()
    if billing_turn_active:
        pooled_api_key, pooled_key_id, pooled_key_label = _cached_keypool_binding(provider)
        if pooled_api_key:
            resolved_api_key = pooled_api_key
            key_id = pooled_key_id
            key_label = pooled_key_label
            key_source = "keypool"
        elif explicit_api_key:
            resolved_api_key = explicit_api_key
            key_source = "env_fallback"
            _warn_env_fallback_for_billed_turn(
                capability,
                provider,
                source="capability_api_key",
            )
        else:
            resolved_api_key = provider_api_key(provider)
            if resolved_api_key:
                key_source = "env_fallback"
                _warn_env_fallback_for_billed_turn(
                    capability,
                    provider,
                    source="provider_api_key",
                )
    else:
        resolved_api_key = explicit_api_key
        if not resolved_api_key:
            pooled_api_key, pooled_key_id, pooled_key_label = _cached_keypool_binding(provider)
            if pooled_api_key:
                resolved_api_key = pooled_api_key
                key_id = pooled_key_id
                key_label = pooled_key_label
                key_source = "keypool"
        if not resolved_api_key:
            resolved_api_key = provider_api_key(provider)
    return ProviderBinding(
        capability=capability,
        provider=provider,
        adapter=capability_adapter(capability, default=adapter_default),
        model=resolved_model,
        api_key=resolved_api_key,
        base_url=provider_base_url(provider),
        key_id=key_id,
        key_label=key_label,
        key_source=key_source,
    )


def is_openai_compatible(binding: ProviderBinding) -> bool:
    return binding.adapter in {"openai_chat", "openai_vision"}


def is_gemini_native(binding: ProviderBinding) -> bool:
    return binding.adapter == "gemini_generate_content"
