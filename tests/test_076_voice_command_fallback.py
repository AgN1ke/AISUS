from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.message_logic as message_logic
import media.voice as voice_mod
from adapters.base import UnifiedMessage


class DummyPTBMessage:
    def __init__(self, text=None, caption=None, reply_to_message=None):
        self.text = text
        self.caption = caption
        self.reply_to_message = reply_to_message
        self.entities = []
        self.caption_entities = []
        self.photo = []
        self.voice = None
        self.video = None
        self.document = None
        self.audio = None
        self._sent = []
        self._sent_kwargs = []
        self._voice_calls = []

    async def reply_text(self, text, **kwargs):
        self._sent.append(text)
        self._sent_kwargs.append(kwargs)

    async def reply_voice(self, voice, **kwargs):
        self._voice_calls.append((voice, kwargs))


def make_update(chat_id, message, bot_id=42, chat_type="group", bot_username="botx"):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_message=message,
        _bot=SimpleNamespace(bot=SimpleNamespace(id=bot_id, username=bot_username)),
    )


def make_unified_message(chat_id, message_id, update, text, bot_username="botx"):
    return UnifiedMessage(
        platform="ptb",
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        caption=None,
        reply_to_message_id=(
            update.effective_message.reply_to_message.message_id
            if update.effective_message.reply_to_message
            else None
        ),
        has_photo=bool(update.effective_message.photo),
        has_voice=bool(update.effective_message.voice),
        has_video=bool(update.effective_message.video),
        has_document=bool(update.effective_message.document),
        raw_update=update,
        bot_username=bot_username,
    )


@pytest.mark.asyncio
async def test_v_command_failure_sends_short_notice_not_source_text(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    async def fake_send_voice_response(_msg, _text, **_kwargs):
        raise TimeoutError("Timed out")

    async def fake_fetch_recent(_chat_id, limit=None):
        return [
            {"role": "assistant", "content": "Дуже довга попередня відповідь бота"},
        ]

    appended = []

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(*_args, **_kwargs):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "send_voice_response", fake_send_voice_response)
    monkeypatch.setattr(message_logic, "fetch_recent", fake_fetch_recent)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="/v@botx")
    msg.entities = [SimpleNamespace(type="mention")]
    upd = make_update(99928, msg)
    um = make_unified_message(99928, 25, upd, "/v@botx")

    await message_logic.process_message(um)

    assert msg._sent == [
        "Не зміг надіслати озвучку останнього повідомлення. Спробуй ще раз трохи пізніше."
    ]
    assert appended[-1] == (
        99928,
        "assistant",
        "Не зміг надіслати озвучку останнього повідомлення. Спробуй ще раз трохи пізніше.",
    )
    assert "Дуже довга попередня відповідь бота" not in msg._sent[0]


@pytest.mark.asyncio
async def test_send_ptb_voice_uses_extended_timeouts(tmp_path):
    ogg = tmp_path / "voice.ogg"
    ogg.write_bytes(b"fake-ogg")

    msg = DummyPTBMessage(text=None)
    update = make_update(123, msg)
    um = make_unified_message(123, 1, update, "")

    await voice_mod._send_ptb_voice(um, str(ogg), reply_to=77)

    assert len(msg._voice_calls) == 1
    _voice, kwargs = msg._voice_calls[0]
    assert kwargs["reply_to_message_id"] == 77
    assert kwargs["read_timeout"] == 180
    assert kwargs["write_timeout"] == 180
    assert kwargs["connect_timeout"] == 30
    assert kwargs["pool_timeout"] == 30
