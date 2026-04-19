from __future__ import annotations

import pytest

from billing.context import BillingContext
from billing.runtime import use_billing_context
from core.provider_registry import resolve_provider_binding


@pytest.mark.asyncio
async def test_provider_binding_uses_user_settings_override(monkeypatch):
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("PROVIDER_GEMINI_API_KEY", "gem-key")

    ctx = BillingContext(
        turn_id="turn-1",
        account_id=10,
        chat_id=20,
        user_id=30,
        meta={
            "user_settings": {
                "chat_provider": "gemini",
                "chat_model": "gemini-2.5-pro",
            }
        },
    )

    async with use_billing_context(ctx):
        binding = resolve_provider_binding("chat_final")

    assert binding.provider == "gemini"
    assert binding.model == "gemini-2.5-pro"
    assert binding.api_key == "gem-key"


@pytest.mark.asyncio
async def test_provider_binding_ignores_invalid_model_override(monkeypatch):
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_PROVIDER", "openai")
    monkeypatch.setenv("CAPABILITY_CHAT_FINAL_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("PROVIDER_OPENAI_API_KEY", "openai-key")

    ctx = BillingContext(
        turn_id="turn-2",
        account_id=10,
        chat_id=20,
        user_id=30,
        meta={
            "user_settings": {
                "chat_provider": "openai",
                "chat_model": "gemini-2.5-pro",
            }
        },
    )

    async with use_billing_context(ctx):
        binding = resolve_provider_binding("chat_final")

    assert binding.provider == "openai"
    assert binding.model == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_explicit_model_arg_overrides_user_selected_model(monkeypatch):
    monkeypatch.setenv("CAPABILITY_VISION_IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("CAPABILITY_VISION_IMAGE_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("PROVIDER_OPENAI_API_KEY", "openai-key")

    ctx = BillingContext(
        turn_id="turn-3",
        account_id=10,
        chat_id=20,
        user_id=30,
        meta={
            "user_settings": {
                "media_provider": "openai",
                "media_model": "gpt-4o",
            }
        },
    )

    async with use_billing_context(ctx):
        binding = resolve_provider_binding("vision_image", model="gpt-4.1-mini")

    assert binding.provider == "openai"
    assert binding.model == "gpt-4.1-mini"
