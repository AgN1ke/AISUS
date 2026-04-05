from __future__ import annotations

from dataclasses import dataclass

import os

from core.env import (
    capability_adapter,
    capability_model,
    capability_provider,
    provider_api_key,
    provider_base_url,
)


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


def resolve_provider_binding(
    capability_name: str,
    *,
    model: str | None = None,
    default_adapter: str = "openai_chat",
) -> ProviderBinding:
    capability = (capability_name or "chat_final").strip() or "chat_final"
    provider = capability_provider(capability)
    adapter_default = _default_adapter_for_provider(provider, default_adapter)
    return ProviderBinding(
        capability=capability,
        provider=provider,
        adapter=capability_adapter(capability, default=adapter_default),
        model=(model or capability_model(capability)).strip(),
        api_key=os.getenv(f"CAPABILITY_{capability.upper()}_API_KEY", "").strip() or provider_api_key(provider),
        base_url=provider_base_url(provider),
    )


def is_openai_compatible(binding: ProviderBinding) -> bool:
    return binding.adapter in {"openai_chat", "openai_vision"}


def is_gemini_native(binding: ProviderBinding) -> bool:
    return binding.adapter == "gemini_generate_content"
