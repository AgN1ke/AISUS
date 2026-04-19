from types import SimpleNamespace

import pytest

import app.message_logic as message_logic
from adapters.base import UnifiedMessage
from media import album_registry


class DummyPTBMessage:
    def __init__(self, reply_to_message=None):
        self.text = None
        self.caption = None
        self.reply_to_message = reply_to_message
        self.entities = []
        self.caption_entities = []
        self.photo = []
        self.voice = None
        self.video = None
        self.document = None
        self.audio = None
        self.media_group_id = None
        self._sent = []
        self._sent_kwargs = []

    async def reply_text(self, text, **kwargs):
        self._sent.append(text)
        self._sent_kwargs.append(kwargs)


def make_update(chat_id, message, bot_id=42, chat_type="group", bot_username="botx"):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_message=message,
        _bot=SimpleNamespace(bot=SimpleNamespace(id=bot_id, username=bot_username)),
    )


def make_album_unified(message_id: int, reply_to_message):
    msg = DummyPTBMessage(reply_to_message=reply_to_message)
    msg.photo = [object()]
    msg.media_group_id = "album-one"
    upd = make_update(99931, msg)
    um = UnifiedMessage(
        platform="ptb",
        chat_id=99931,
        message_id=message_id,
        text="",
        caption=None,
        reply_to_message_id=reply_to_message.message_id,
        has_photo=True,
        has_voice=False,
        has_video=False,
        has_document=False,
        raw_update=upd,
        media_group_id="album-one",
        bot_username="botx",
    )
    return msg, um


@pytest.mark.asyncio
async def test_album_reply_is_processed_once_for_whole_media_group(monkeypatch):
    album_registry._ALBUMS.clear()
    album_registry._MESSAGE_INDEX.clear()
    album_registry._PROCESSING.clear()
    album_registry._HANDLED.clear()

    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    observed = {"run_simple_calls": 0, "sleep_calls": 0}

    reply_to = SimpleNamespace(
        message_id=70,
        text="старе повідомлення бота",
        caption=None,
        from_user=SimpleNamespace(id=42, username="botx"),
        photo=[],
        voice=None,
        video=None,
        document=None,
        audio=None,
    )

    msg1, um1 = make_album_unified(31, reply_to)
    msg2, um2 = make_album_unified(32, reply_to)
    msg3, um3 = make_album_unified(33, reply_to)

    async def fake_sleep(_seconds):
        observed["sleep_calls"] += 1
        message_logic.observe_album_message(um2)
        message_logic.observe_album_message(um3)

    async def fake_handle_ptb_mention(_update, _context, _bot_username):
        return ("поясни альбом", "image")

    async def fake_run_simple(_chat_id, user_text, **_kwargs):
        observed["run_simple_calls"] += 1
        return f"OK: {user_text}"

    async def fake_append(*_args, **_kwargs):
        return None

    async def fake_budget(*_args, **_kwargs):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "handle_ptb_mention", fake_handle_ptb_mention)
    monkeypatch.setattr(message_logic, "run_simple", fake_run_simple)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)
    monkeypatch.setattr(message_logic.asyncio, "sleep", fake_sleep)

    await message_logic.process_message(um1)
    await message_logic.process_message(um2)
    await message_logic.process_message(um3)

    assert observed["sleep_calls"] == 1
    assert observed["run_simple_calls"] == 1
    assert msg1._sent == ["OK: поясни альбом"]
    assert msg2._sent == []
    assert msg3._sent == []
