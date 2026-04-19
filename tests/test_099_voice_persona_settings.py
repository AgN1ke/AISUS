from __future__ import annotations

from types import SimpleNamespace

import pytest

import billing.commands as commands
import media.voice as voice


def test_synthesize_chunk_uses_runtime_voice_override(monkeypatch, tmp_path):
    captured: dict[str, str] = {}

    class DummyResponse:
        def read(self) -> bytes:
            return b"audio"

    class DummySpeech:
        def create(self, **kwargs):
            captured.update(kwargs)
            return DummyResponse()

    class DummyClient:
        audio = SimpleNamespace(speech=DummySpeech())

    monkeypatch.setattr(voice, "_tts_client", lambda: DummyClient())
    monkeypatch.setattr(voice, "tts_model", lambda: "gpt-4o-mini-tts")
    monkeypatch.setattr(voice, "vocalizer_voice", lambda: "alloy")
    monkeypatch.setattr(voice, "current_runtime_user_settings", lambda: {"voice_id": "nova"})
    monkeypatch.setattr(voice, "MEDIA_TMP", tmp_path)

    path = voice._synthesize_chunk_sync("hello", 1)

    assert captured["voice"] == "nova"
    assert captured["model"] == "gpt-4o-mini-tts"
    assert path.endswith(".ogg")


@pytest.mark.asyncio
async def test_model_callback_voice_select_persists_setting(monkeypatch):
    stored: dict[str, str] = {}

    async def fake_get_user_settings(user_id):
        return dict(stored)

    async def fake_set_user_setting(user_id, key, value):
        if value is None:
            stored.pop(key, None)
        else:
            stored[key] = value

    monkeypatch.setattr(commands, "get_user_settings", fake_get_user_settings)
    monkeypatch.setattr(commands, "set_user_setting", fake_set_user_setting)

    edits = {}
    answers = []

    class DummyCallback:
        data = "mtmodel:voice_select:nova"
        from_user = SimpleNamespace(id=42)
        message = SimpleNamespace(chat_id=100, message_id=7)

        async def answer(self, text=None, show_alert=False):
            answers.append((text, show_alert))

        async def edit_message_text(self, text, **kwargs):
            edits["text"] = text
            edits["kwargs"] = kwargs

    update = SimpleNamespace(callback_query=DummyCallback())

    handled = await commands.try_handle_callback(update, "smartest_bot")

    assert handled is True
    assert stored["voice_id"] == "nova"
    assert "nova" in edits["text"].lower()
    assert answers


@pytest.mark.asyncio
async def test_model_callback_persona_select_persists_setting(monkeypatch):
    stored: dict[str, str] = {}

    async def fake_get_user_settings(user_id):
        return dict(stored)

    async def fake_set_user_setting(user_id, key, value):
        if value is None:
            stored.pop(key, None)
        else:
            stored[key] = value

    monkeypatch.setattr(commands, "get_user_settings", fake_get_user_settings)
    monkeypatch.setattr(commands, "set_user_setting", fake_set_user_setting)

    edits = {}
    answers = []

    class DummyCallback:
        data = "mtmodel:persona_select:technical"
        from_user = SimpleNamespace(id=42)
        message = SimpleNamespace(chat_id=100, message_id=7)

        async def answer(self, text=None, show_alert=False):
            answers.append((text, show_alert))

        async def edit_message_text(self, text, **kwargs):
            edits["text"] = text
            edits["kwargs"] = kwargs

    update = SimpleNamespace(callback_query=DummyCallback())

    handled = await commands.try_handle_callback(update, "smartest_bot")

    assert handled is True
    assert stored["persona_slug"] == "technical"
    assert "technical" in edits["text"].lower()
    assert answers
