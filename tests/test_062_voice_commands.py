from types import SimpleNamespace

import pytest

import app.message_logic as message_logic
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

    async def reply_text(self, text, **kwargs):
        self._sent.append(text)
        self._sent_kwargs.append(kwargs)


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
async def test_a_command_sends_voice(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    sent = {}
    appended = []

    async def fake_send_voice_response(_msg, text, **_kwargs):
        sent["text"] = text

    async def fail_run_simple(*_args, **_kwargs):
        raise AssertionError("run_simple should not be called for /a")

    async def fail_run_search(*_args, **_kwargs):
        raise AssertionError("run_search should not be called for /a")

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "send_voice_response", fake_send_voice_response)
    monkeypatch.setattr(message_logic, "run_simple", fail_run_simple)
    monkeypatch.setattr(message_logic, "run_search", fail_run_search)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="@botx /a Озвуч це речення")
    msg.entities = [SimpleNamespace(type="mention")]
    upd = make_update(99914, msg)
    um = make_unified_message(99914, 9, upd, "@botx /a Озвуч це речення")

    await message_logic.process_message(um)

    assert sent["text"] == "Озвуч це речення"
    assert msg._sent == []
    assert appended[0][1] == "system"
    assert appended[1] == (99914, "user", "/a Озвуч це речення")
    assert appended[-1] == (99914, "assistant", "Озвуч це речення")


@pytest.mark.asyncio
async def test_targeted_a_command_with_bot_username_works(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    sent = {}

    async def fake_send_voice_response(_msg, text, **_kwargs):
        sent["text"] = text

    async def fake_append(*_args, **_kwargs):
        return None

    async def fake_budget(*_args, **_kwargs):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "send_voice_response", fake_send_voice_response)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="/a@botx Озвуч це речення")
    msg.entities = [SimpleNamespace(type="mention")]
    upd = make_update(99924, msg)
    um = make_unified_message(99924, 21, upd, "/a@botx Озвуч це речення")

    await message_logic.process_message(um)

    assert sent["text"] == "Озвуч це речення"
    assert msg._sent == []


@pytest.mark.asyncio
async def test_v_command_sends_last_assistant_reply(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    sent = {}
    appended = []

    async def fake_send_voice_response(_msg, text, **_kwargs):
        sent["text"] = text

    async def fake_fetch_recent(_chat_id, limit=None):
        return [
            {"role": "user", "content": "привіт"},
            {"role": "assistant", "content": "Остання відповідь бота"},
        ]

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "send_voice_response", fake_send_voice_response)
    monkeypatch.setattr(message_logic, "fetch_recent", fake_fetch_recent)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="@botx /v")
    msg.entities = [SimpleNamespace(type="mention")]
    upd = make_update(99915, msg)
    um = make_unified_message(99915, 10, upd, "@botx /v")

    await message_logic.process_message(um)

    assert sent["text"] == "Остання відповідь бота"
    assert msg._sent == []
    assert appended[-1] == (99915, "assistant", "Остання відповідь бота")


@pytest.mark.asyncio
async def test_targeted_v_command_with_bot_username_works(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    sent = {}

    async def fake_send_voice_response(_msg, text, **_kwargs):
        sent["text"] = text

    async def fake_fetch_recent(_chat_id, limit=None):
        return [
            {"role": "assistant", "content": "Остання відповідь бота"},
        ]

    async def fake_append(*_args, **_kwargs):
        return None

    async def fake_budget(*_args, **_kwargs):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "send_voice_response", fake_send_voice_response)
    monkeypatch.setattr(message_logic, "fetch_recent", fake_fetch_recent)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="/v@botx")
    msg.entities = [SimpleNamespace(type="mention")]
    upd = make_update(99925, msg)
    um = make_unified_message(99925, 22, upd, "/v@botx")

    await message_logic.process_message(um)

    assert sent["text"] == "Остання відповідь бота"
    assert msg._sent == []


@pytest.mark.asyncio
async def test_current_voice_message_uses_voice_reply_transport(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    sent = {}
    appended = []

    async def fake_send_voice_response(_msg, text, **_kwargs):
        sent["text"] = text

    async def fake_handle_ptb_mention(_update, _context, _bot_username):
        return ("Що ти сказав?", "voice")

    async def fake_run_simple(_chat_id, user_text, **_kwargs):
        return "Почув тебе, відпочивай."

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "send_voice_response", fake_send_voice_response)
    monkeypatch.setattr(message_logic, "handle_ptb_mention", fake_handle_ptb_mention)
    monkeypatch.setattr(message_logic, "run_simple", fake_run_simple)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="@botx")
    msg.entities = [SimpleNamespace(type="mention")]
    msg.voice = SimpleNamespace(file_id="voice-1")
    upd = make_update(99916, msg)
    um = make_unified_message(99916, 11, upd, "@botx")
    um.has_voice = True

    await message_logic.process_message(um)

    assert sent["text"] == "Почув тебе, відпочивай."
    assert msg._sent == []
    assert appended[-1] == (99916, "assistant", "Почув тебе, відпочивай.")


@pytest.mark.asyncio
async def test_current_voice_message_is_persisted_as_transcript_user_turn(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    appended = []

    async def fake_send_voice_response(_msg, _text, **_kwargs):
        return None

    async def fake_handle_ptb_mention(_update, _context, _bot_username):
        return ("Я помився і зараз вже буду спати.", "voice")

    async def fake_run_simple(_chat_id, user_text, **_kwargs):
        return f"Ок, почув: {user_text}"

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "send_voice_response", fake_send_voice_response)
    monkeypatch.setattr(message_logic, "handle_ptb_mention", fake_handle_ptb_mention)
    monkeypatch.setattr(message_logic, "run_simple", fake_run_simple)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    reply_to = SimpleNamespace(
        message_id=50,
        text="Текст бота",
        caption=None,
        from_user=SimpleNamespace(id=42, username="botx"),
        photo=[],
        voice=None,
        video=None,
        document=None,
        audio=None,
    )
    msg = DummyPTBMessage(text=None, reply_to_message=reply_to)
    msg.voice = SimpleNamespace(file_id="voice-2")
    upd = make_update(99926, msg)
    um = make_unified_message(99926, 23, upd, "")
    um.has_voice = True

    await message_logic.process_message(um)

    assert appended[0][1] == "system"
    assert appended[1] == (99926, "user", "Я помився і зараз вже буду спати.")
    assert appended[-1] == (
        99926,
        "assistant",
        "Ок, почув: Я помився і зараз вже буду спати.",
    )


@pytest.mark.asyncio
async def test_text_reply_to_bot_voice_is_processed_without_mention(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    appended = []

    async def fake_handle_ptb_mention(_update, _context, _bot_username):
        return ("Що ти мала на увазі у попередньому войсі?", "voice")

    async def fake_run_simple(_chat_id, user_text, **_kwargs):
        return f"Відповідаю на reply: {user_text}"

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "handle_ptb_mention", fake_handle_ptb_mention)
    monkeypatch.setattr(message_logic, "run_simple", fake_run_simple)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    reply_to = SimpleNamespace(
        message_id=51,
        text=None,
        caption=None,
        from_user=SimpleNamespace(id=42, username="botx"),
        photo=[],
        voice=SimpleNamespace(file_id="bot-voice-1"),
        video=None,
        document=None,
        audio=None,
    )
    msg = DummyPTBMessage(text="Та ні, я про інше", reply_to_message=reply_to)
    upd = make_update(99927, msg)
    um = make_unified_message(99927, 24, upd, "Та ні, я про інше")

    await message_logic.process_message(um)

    assert msg._sent == ["Відповідаю на reply: Що ти мала на увазі у попередньому войсі?"]
    assert appended[0][1] == "system"
    assert appended[1] == (99927, "user", "Та ні, я про інше")
    assert appended[-1] == (
        99927,
        "assistant",
        "Відповідаю на reply: Що ти мала на увазі у попередньому войсі?",
    )
