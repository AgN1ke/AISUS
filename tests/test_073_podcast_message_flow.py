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
async def test_explicit_podcast_request_stays_fail_closed_without_readiness(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    async def fake_get_podcast_pending(_chat_id):
        return None

    async def fail_set_podcast_pending(*_args, **_kwargs):
        raise AssertionError("pending podcast state should not be created without readiness")

    async def fail_run_simple(*_args, **_kwargs):
        raise AssertionError("run_simple should not be called for podcast request")

    async def fail_run_search(*_args, **_kwargs):
        raise AssertionError("run_search should not be called for podcast request")

    appended = []

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "get_podcast_pending", fake_get_podcast_pending)
    monkeypatch.setattr(message_logic, "set_podcast_pending", fail_set_podcast_pending)
    monkeypatch.setattr(message_logic, "podcast_runtime_ready", lambda: False)
    monkeypatch.setattr(message_logic, "run_simple", fail_run_simple)
    monkeypatch.setattr(message_logic, "run_search", fail_run_search)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="@botx зроби на цю тему подкаст")
    msg.entities = [SimpleNamespace(type="mention")]
    upd = make_update(99915, msg)
    um = make_unified_message(99915, 10, upd, "@botx зроби на цю тему подкаст")

    await message_logic.process_message(um)

    assert "подкастів зараз не налаштований" in msg._sent[0]
    assert appended[0][1] == "system"
    assert appended[1] == (99915, "user", "зроби на цю тему подкаст")
    assert appended[-1][1] == "assistant"


@pytest.mark.asyncio
async def test_explicit_podcast_request_creates_confirmation_when_ready(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    async def fake_get_podcast_pending(_chat_id):
        return None

    saved = {}

    async def fake_set_podcast_pending(chat_id, payload):
        saved["chat_id"] = chat_id
        saved["payload"] = payload

    async def fake_clear_podcast_dossier(_chat_id):
        saved["dossier_cleared"] = True

    async def fake_fetch_recent(_chat_id, limit=None):
        assert limit == 12
        return [
            {"role": "assistant", "content": "Ми говорили про одомашнення бавовни, льону, конопель і кропиви."},
        ]

    async def fail_run_simple(*_args, **_kwargs):
        raise AssertionError("run_simple should not be called for podcast request")

    async def fail_run_search(*_args, **_kwargs):
        raise AssertionError("run_search should not be called for podcast request")

    appended = []

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "get_podcast_pending", fake_get_podcast_pending)
    monkeypatch.setattr(message_logic, "set_podcast_pending", fake_set_podcast_pending)
    monkeypatch.setattr(message_logic, "clear_podcast_dossier", fake_clear_podcast_dossier)
    monkeypatch.setattr(message_logic, "fetch_recent", fake_fetch_recent)
    monkeypatch.setattr(message_logic, "podcast_runtime_ready", lambda: True)
    monkeypatch.setattr(message_logic, "run_simple", fail_run_simple)
    monkeypatch.setattr(message_logic, "run_search", fail_run_search)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="@botx а зроби нам на цю тему подкаст")
    msg.entities = [SimpleNamespace(type="mention")]
    upd = make_update(99916, msg)
    um = make_unified_message(99916, 11, upd, "@botx а зроби нам на цю тему подкаст")

    await message_logic.process_message(um)

    assert saved["chat_id"] == 99916
    assert saved["dossier_cleared"] is True
    assert "одомашнення бавовни" in saved["payload"]["topic_label"]
    assert "Ти хочеш зробити подкаст" in msg._sent[0]
    assert "одомашнення бавовни" in msg._sent[0]
    assert appended[-1][1] == "assistant"


@pytest.mark.asyncio
async def test_podcast_confirmation_uses_pending_state(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    async def fake_get_podcast_pending(_chat_id):
        return {
            "topic_label": "одомашнення бавовни та інших волокон",
            "style_instruction": "",
            "request_text": "зроби подкаст",
            "source_scope": "recent_context",
            "source_message_id": None,
            "anchor_excerpt": "одомашнення бавовни та інших волокон",
        }

    cleared = {"ok": False}
    stored = {}

    async def fake_clear_podcast_pending(_chat_id):
        cleared["ok"] = True

    async def fake_set_podcast_dossier(chat_id, payload):
        stored["chat_id"] = chat_id
        stored["payload"] = payload

    async def fake_build_podcast_dossier(chat_id, pending):
        assert chat_id == 99917
        assert "одомашнення бавовни" in pending["topic_label"]
        return SimpleNamespace(
            recent_turns=["turn 1"],
            core_facts=["fact 1"],
            long_memory_notes=["long 1"],
            to_dict=lambda: {
                "topic_label": pending["topic_label"],
                "assembled_text": "[PODCAST-DOSSIER]\n...",
            },
        )

    async def fail_run_simple(*_args, **_kwargs):
        raise AssertionError("run_simple should not be called for podcast confirmation")

    async def fail_run_search(*_args, **_kwargs):
        raise AssertionError("run_search should not be called for podcast confirmation")

    appended = []

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "get_podcast_pending", fake_get_podcast_pending)
    monkeypatch.setattr(message_logic, "clear_podcast_pending", fake_clear_podcast_pending)
    monkeypatch.setattr(message_logic, "set_podcast_dossier", fake_set_podcast_dossier)
    monkeypatch.setattr(message_logic, "build_podcast_dossier", fake_build_podcast_dossier)
    monkeypatch.setattr(message_logic, "podcast_runtime_ready", lambda: True)
    monkeypatch.setattr(message_logic, "run_simple", fail_run_simple)
    monkeypatch.setattr(message_logic, "run_search", fail_run_search)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="@botx так, але у форматі дискусії")
    msg.entities = [SimpleNamespace(type="mention")]
    upd = make_update(99917, msg)
    um = make_unified_message(99917, 12, upd, "@botx так, але у форматі дискусії")

    await message_logic.process_message(um)

    assert cleared["ok"] is True
    assert stored["chat_id"] == 99917
    assert stored["payload"]["assembled_text"].startswith("[PODCAST-DOSSIER]")
    assert "Підтвердження теми прийняв" in msg._sent[0]
    assert "форматі дискусії" in msg._sent[0]
    assert "dossier" in msg._sent[0]
    assert appended[-1][1] == "assistant"
