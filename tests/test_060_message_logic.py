import os
from types import SimpleNamespace

import pytest

import app.message_logic as message_logic
from adapters.base import UnifiedMessage
from agent.planner import PlanDecision


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
async def test_auth_flow_with_password(monkeypatch):
    os.environ["CHAT_JOIN_PASSWORD"] = "supersecret"

    async def fake_get_settings(_chat_id):
        return {}

    saved = {}

    async def fake_upsert_settings(chat_id, **kwargs):
        saved["chat_id"] = chat_id
        saved["kwargs"] = kwargs

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "upsert_settings", fake_upsert_settings)

    msg = DummyPTBMessage(text="@botx supersecret")
    upd = make_update(99906, msg)
    um = make_unified_message(99906, 1, upd, "@botx supersecret")

    await message_logic.process_message(um)

    assert any("Пароль прийнято" in m for m in msg._sent)
    assert saved["chat_id"] == 99906
    assert saved["kwargs"]["auth_ok"] is True


@pytest.mark.asyncio
async def test_auth_flow_accepts_reply_to_bot_password(monkeypatch):
    os.environ["CHAT_JOIN_PASSWORD"] = "supersecret"

    async def fake_get_settings(_chat_id):
        return {}

    async def fake_upsert_settings(*_args, **_kwargs):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "upsert_settings", fake_upsert_settings)

    reply_to = SimpleNamespace(
        message_id=10,
        text="🔒 Напиши пароль",
        caption=None,
        from_user=SimpleNamespace(id=42, username="botx"),
        photo=[],
        voice=None,
        video=None,
        document=None,
        audio=None,
    )
    msg = DummyPTBMessage(text="supersecret", reply_to_message=reply_to)
    upd = make_update(99907, msg)
    um = make_unified_message(99907, 2, upd, "supersecret")

    await message_logic.process_message(um)

    assert any("Пароль прийнято" in m for m in msg._sent)


@pytest.mark.asyncio
async def test_authed_group_ignores_unaddressed_message(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    async def fail_run_simple(*_args, **_kwargs):
        raise AssertionError(
            "run_simple should not be called for unaddressed group messages"
        )

    async def fail_run_search(*_args, **_kwargs):
        raise AssertionError(
            "run_search should not be called for unaddressed group messages"
        )

    async def fake_append(*_args, **_kwargs):
        raise AssertionError(
            "memory append should not be called for unaddressed group messages"
        )

    async def fake_budget(*_args, **_kwargs):
        raise AssertionError(
            "memory budget should not be called for unaddressed group messages"
        )

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "run_simple", fail_run_simple)
    monkeypatch.setattr(message_logic, "run_search", fail_run_search)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    msg = DummyPTBMessage(text="випадкове повідомлення")
    upd = make_update(99908, msg)
    um = make_unified_message(99908, 3, upd, "випадкове повідомлення")

    await message_logic.process_message(um)

    assert msg._sent == []


@pytest.mark.asyncio
async def test_authed_group_reply_to_bot_is_allowed(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    async def fake_run_simple(_chat_id, user_text, **_kwargs):
        return f"OK: {user_text}"

    appended = []

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "run_simple", fake_run_simple)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    reply_to = SimpleNamespace(
        message_id=11,
        text="старе повідомлення бота",
        caption=None,
        from_user=SimpleNamespace(id=42, username="botx"),
        photo=[],
        voice=None,
        video=None,
        document=None,
        audio=None,
    )
    msg = DummyPTBMessage(text="відповідь без @mention", reply_to_message=reply_to)
    upd = make_update(99909, msg)
    um = make_unified_message(99909, 4, upd, "відповідь без @mention")

    await message_logic.process_message(um)

    assert msg._sent == ["OK: відповідь без @mention"]
    assert msg._sent_kwargs[-1]["parse_mode"] == "HTML"
    assert msg._sent_kwargs[-1]["disable_web_page_preview"] is True
    assert appended[0][0] == 99909
    assert appended[0][1] == "system"
    assert "[CHAT-TURN]" in appended[0][2]
    assert appended[1] == (99909, "user", "відповідь без @mention")
    assert appended[-1] == (99909, "assistant", "OK: відповідь без @mention")


@pytest.mark.asyncio
async def test_clear_context_command_clears_chat_memory(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    cleared = {}

    async def fake_clear_all(chat_id):
        cleared["chat_id"] = chat_id

    async def fail_run_simple(*_args, **_kwargs):
        raise AssertionError("run_simple should not be called for /c")

    async def fail_run_search(*_args, **_kwargs):
        raise AssertionError("run_search should not be called for /c")

    async def fail_append(*_args, **_kwargs):
        raise AssertionError("memory append should not be called for /c")

    async def fail_budget(*_args, **_kwargs):
        raise AssertionError("memory budget should not be called for /c")

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "run_simple", fail_run_simple)
    monkeypatch.setattr(message_logic, "run_search", fail_run_search)
    monkeypatch.setattr(message_logic.memory_manager, "clear_all", fake_clear_all)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fail_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fail_budget)

    msg = DummyPTBMessage(text="/c@botx")
    upd = make_update(999091, msg)
    um = make_unified_message(999091, 40, upd, "/c@botx")

    await message_logic.process_message(um)

    assert cleared["chat_id"] == 999091
    assert any("очищено" in m.lower() for m in msg._sent)


@pytest.mark.asyncio
async def test_authed_group_explicit_search_uses_agent_route(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    def fake_plan_message(_task):
        return PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=False,
            planner_source="test",
            notes="forced_search",
        )

    called = {}

    async def fake_run_search(_chat_id, user_text, use_reasoning=False, **_kwargs):
        called["user_text"] = user_text
        called["use_reasoning"] = use_reasoning
        return "SEARCH: OK"

    async def fail_run_simple(*_args, **_kwargs):
        raise AssertionError("run_simple should not be called for forced search route")

    appended = []

    async def fake_append(chat_id, role, content):
        appended.append((chat_id, role, content))

    async def fake_budget(_chat_id):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "plan_message", fake_plan_message)
    monkeypatch.setattr(message_logic, "run_search", fake_run_search)
    monkeypatch.setattr(message_logic, "run_simple", fail_run_simple)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    reply_to = SimpleNamespace(
        message_id=12,
        text="старе повідомлення бота",
        caption=None,
        from_user=SimpleNamespace(id=42, username="botx"),
        photo=[],
        voice=None,
        video=None,
        document=None,
        audio=None,
    )
    msg = DummyPTBMessage(text="пошукай новини про OpenAI", reply_to_message=reply_to)
    upd = make_update(99910, msg)
    um = make_unified_message(99910, 5, upd, "пошукай новини про OpenAI")

    await message_logic.process_message(um)

    assert called["user_text"] == "пошукай новини про OpenAI"
    assert called["use_reasoning"] is False
    assert msg._sent == ["SEARCH: OK\n\n⚠️УВАГА! ВІДБУВСЯ ПОШУК!⚠️"]
    assert msg._sent_kwargs[-1]["parse_mode"] == "HTML"
    assert appended[0][1] == "system"
    assert "[CHAT-TURN]" in appended[0][2]
    assert appended[1][1] == "user"
    assert appended[-1] == (99910, "assistant", "SEARCH: OK\n\n⚠️УВАГА! ВІДБУВСЯ ПОШУК!⚠️")


@pytest.mark.asyncio
async def test_reply_geometry_is_passed_to_runtime(monkeypatch):
    async def fake_get_settings(_chat_id):
        return {"auth_ok": True}

    captured = {}

    async def fake_run_simple(_chat_id, user_text, **kwargs):
        captured["user_text"] = user_text
        captured["turn_context_msgs"] = kwargs.get("turn_context_msgs") or []
        return "OK: geometry"

    async def fake_handle_ptb_mention(_update, _context, _bot_username):
        return "Проаналізуй наведене медіа і відповідай по суті завдання."

    async def fake_append(*_args, **_kwargs):
        return None

    async def fake_budget(*_args, **_kwargs):
        return None

    monkeypatch.setattr(message_logic, "get_settings", fake_get_settings)
    monkeypatch.setattr(message_logic, "run_simple", fake_run_simple)
    monkeypatch.setattr(message_logic, "handle_ptb_mention", fake_handle_ptb_mention)
    monkeypatch.setattr(message_logic.memory_manager, "append_message", fake_append)
    monkeypatch.setattr(message_logic.memory_manager, "ensure_budget", fake_budget)

    reply_to = SimpleNamespace(
        message_id=44,
        text="це мем про конспірологію",
        caption=None,
        from_user=SimpleNamespace(
            id=99,
            username="mikita",
            first_name="Микита",
            last_name="Загамула",
        ),
        photo=[object()],
        voice=None,
        video=None,
        document=None,
        audio=None,
    )
    msg = DummyPTBMessage(text="@botx поясни", reply_to_message=reply_to)
    msg.entities = [SimpleNamespace(type="mention")]
    upd = make_update(99911, msg)
    um = make_unified_message(99911, 6, upd, "@botx поясни")

    await message_logic.process_message(um)

    turn_context = "\n".join(
        item["content"]
        for item in captured["turn_context_msgs"]
        if item["role"] == "system"
    )
    assert (
        captured["user_text"]
        == "Проаналізуй наведене медіа і відповідай по суті завдання."
    )
    assert "reply_target_author: Микита Загамула @mikita" in turn_context
    assert "reply_target_media_kind: image" in turn_context
    assert "reply_target_text: це мем про конспірологію" in turn_context
