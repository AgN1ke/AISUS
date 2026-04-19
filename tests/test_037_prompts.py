import os

import pytest

from billing.context import BillingContext
from billing.runtime import use_billing_context

from core.prompts import (
    capability_system_prompt,
    configured_chat_persona_prompt,
    format_env_prompt,
    resolve_persona_for_user,
    search_synthesis_system_prompt,
)


def test_format_env_prompt_handles_none_and_pipe_separator():
    assert format_env_prompt(None) == ""
    assert format_env_prompt("рядок 1 | рядок 2") == "рядок 1\nрядок 2"


def test_capability_system_prompt_uses_env_persona(monkeypatch):
    monkeypatch.setenv("SYSTEM_MESSAGES_GPT_PROMPT", "Ти персона.")

    assert configured_chat_persona_prompt() == "Ти персона."
    chat_prompt = capability_system_prompt("chat_final")
    assert "Ти персона." in chat_prompt
    assert "Telegram" in chat_prompt

    vision_prompt = capability_system_prompt("vision_image")
    assert "Ти персона." in vision_prompt
    assert "[СЛУЖБОВА ІНСТРУКЦІЯ CAPABILITY]" in vision_prompt
    assert "[СЛУЖБОВА ІНСТРУКЦІЯ TRANSPORT]" in vision_prompt
    assert "[SEARCH]" in vision_prompt


def test_search_synthesis_prompt_mentions_inline_citations(monkeypatch):
    monkeypatch.setenv("SYSTEM_MESSAGES_GPT_PROMPT", "Ти персона.")

    prompt = search_synthesis_system_prompt()

    assert "Ти персона." in prompt
    assert "inline citations" in prompt
    assert "[1], [2]" in prompt
    assert "Не додавай окремий блок джерел" in prompt


