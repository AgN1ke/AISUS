from types import SimpleNamespace

import pytest

from media.router import handle_ptb_mention
from memory import memory_manager


class DummyMsg:
    def __init__(self, chat_id, mid, text=None, caption=None, reply_to=None):
        self.message_id = mid
        self.chat_id = chat_id
        self.text = text
        self.caption = caption
        self.photo = []
        self.video = None
        self.voice = None
        self.audio = None
        self.document = None
        self.reply_to_message = reply_to
        self.entities = []
        self.caption_entities = []


class DummyUpdate:
    def __init__(self, chat_id, msg):
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.effective_message = msg


class DummyCtx:
    bot = SimpleNamespace(username="mybot")


@pytest.mark.asyncio
async def test_voice_mention_adds_transcript_and_post_text(monkeypatch):
    chat = 99918
    stored = {}

    async def fake_download(msg, context):
        return {
            "type": "voice",
            "paths": ["fake.ogg"],
            "text": "підпис до войса",
        }

    async def fake_transcribe(_path):
        return "привіт, це тестовий транскрипт"

    async def fake_append(_chat_id, _role, content):
        stored["content"] = content

    async def fake_budget(*_args, **_kwargs):
        return None

    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr("media.router.transcribe_audio", fake_transcribe)
    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)

    msg = DummyMsg(chat, 32, text="@mybot")
    msg.voice = object()
    upd = DummyUpdate(chat, msg)
    out, route_kind = await handle_ptb_mention(upd, DummyCtx, "mybot")

    assert "target_post_text: підпис до войса" in stored["content"]
    assert "audio_transcript: привіт, це тестовий транскрипт" in stored["content"]
    assert route_kind == "voice"
    assert out == "привіт, це тестовий транскрипт"
