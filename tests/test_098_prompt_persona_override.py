from __future__ import annotations

import pytest

from billing.context import BillingContext
from billing.runtime import use_billing_context
from core.prompts import capability_system_prompt, resolve_persona_for_user, search_synthesis_system_prompt


@pytest.mark.asyncio
async def test_persona_override_is_applied_from_runtime_user_settings(monkeypatch):
    monkeypatch.setenv("SYSTEM_MESSAGES_GPT_PROMPT", "Base persona.")
    ctx = BillingContext(
        turn_id="turn-persona",
        account_id=1,
        chat_id=2,
        user_id=3,
        meta={"user_settings": {"persona_slug": "technical"}},
    )

    async with use_billing_context(ctx):
        resolved = resolve_persona_for_user()
        prompt = capability_system_prompt("chat_final")
        synthesis = search_synthesis_system_prompt()

    assert "Base persona." in resolved
    assert "прагматичний інженер" in resolved
    assert "прагматичний інженер" in prompt
    assert "прагматичний інженер" in synthesis
