import os

from core.prompts import (
    LEGACY_DEFAULT_IMAGE_CAPTION_AFFIX,
    LEGACY_DEFAULT_IMAGE_MESSAGE_AFFIX,
    LEGACY_DEFAULT_IMAGE_SCENE_AFFIX,
    capability_system_prompt,
    configured_chat_persona_prompt,
    format_env_prompt,
    search_synthesis_system_prompt,
)
from src.heroku_config_parser import ConfigReader


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


def test_legacy_config_reader_uses_centralized_defaults(monkeypatch):
    for key in (
        "SYSTEM_MESSAGES_WELCOME_MESSAGE",
        "SYSTEM_MESSAGES_VOICE_MESSAGE_AFFIX",
        "SYSTEM_MESSAGES_IMAGE_MESSAGE_AFFIX",
        "SYSTEM_MESSAGES_IMAGE_CAPTION_AFFIX",
        "SYSTEM_MESSAGES_IMAGE_SENCE_AFFIX",
        "PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = ConfigReader()

    assert cfg.image_message_affix == LEGACY_DEFAULT_IMAGE_MESSAGE_AFFIX
    assert cfg.image_caption_affix == LEGACY_DEFAULT_IMAGE_CAPTION_AFFIX
    assert cfg.image_sence_affix == LEGACY_DEFAULT_IMAGE_SCENE_AFFIX
