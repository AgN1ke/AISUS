import asyncio
from types import SimpleNamespace

import pytest

import app.message_logic as message_logic
from adapters.base import MessageGeometry, ReplyTarget, UnifiedMessage
from agent.planner import PlanDecision
from app.chat_geometry import render_turn_context_messages


class DummyPTBMessage:
    def __init__(self):
        self._sent = []
        self._sent_kwargs = []

    async def reply_text(self, text, **kwargs):
        self._sent.append(text)
        self._sent_kwargs.append(kwargs)


def make_unified_message(text: str = "", bot_username: str = "botx") -> UnifiedMessage:
    raw_message = DummyPTBMessage()
    update = SimpleNamespace(
        effective_message=raw_message,
        effective_chat=SimpleNamespace(id=99950, type="group"),
        _bot=SimpleNamespace(bot=SimpleNamespace(id=42, username=bot_username)),
    )
    return UnifiedMessage(
        platform="ptb",
        chat_id=99950,
        message_id=77,
        text=text,
        caption=None,
        reply_to_message_id=None,
        has_photo=False,
        has_voice=False,
        has_video=False,
        has_document=False,
        raw_update=update,
        bot_username=bot_username,
    )


@pytest.mark.asyncio
async def test_process_message_skips_duplicate_message_id(monkeypatch):
    message_logic._RECENT_MESSAGE_KEYS.clear()
    calls = []

    async def fake_process_inner(msg, trace):
        calls.append(trace)
        await asyncio.sleep(0.01)

    monkeypatch.setattr(message_logic, "_process_message_inner", fake_process_inner)

    msg = make_unified_message("@botx hi")
    await asyncio.gather(
        message_logic.process_message(msg),
        message_logic.process_message(msg),
    )

    assert calls == ["ptb:99950:77"]
    message_logic._RECENT_MESSAGE_KEYS.clear()


@pytest.mark.asyncio
async def test_check_access_returns_auth_prompt_for_unauthed_addressed_message():
    msg = make_unified_message("@botx привіт")
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="привіт",
        addressed_via_mention=True,
        addressed=True,
    )
    session = message_logic.SessionState(chat_id=msg.chat_id, authed=False)

    result = await message_logic.check_access(msg, geometry, session)

    assert result.allowed is False
    assert result.should_stop is True
    assert result.deny_reason == "auth_required"
    assert "🔒" in (result.response_text or "")


@pytest.mark.asyncio
async def test_check_access_accepts_valid_password(monkeypatch):
    saved = {}

    async def fake_upsert_settings(chat_id, **kwargs):
        saved["chat_id"] = chat_id
        saved["kwargs"] = kwargs

    monkeypatch.setattr(message_logic, "upsert_settings", fake_upsert_settings)
    monkeypatch.setattr(message_logic, "chat_join_password", lambda: "supersecret")

    msg = make_unified_message("@botx supersecret")
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="supersecret",
        addressed_via_mention=True,
        addressed=True,
    )
    session = message_logic.SessionState(chat_id=msg.chat_id, authed=False)

    result = await message_logic.check_access(msg, geometry, session)

    assert result.allowed is False
    assert result.should_stop is True
    assert result.session_state.authed is True
    assert "Пароль прийнято" in (result.response_text or "")
    assert saved["chat_id"] == msg.chat_id
    assert saved["kwargs"]["auth_ok"] is True


@pytest.mark.asyncio
async def test_build_user_task_marks_instruction_on_target():
    msg = make_unified_message("@botx поясни мем")
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="поясни мем",
        addressed_via_mention=True,
        addressed=True,
        target_media_kind="image",
        reply_target=ReplyTarget(
            message_id=123,
            text="це мем про змову",
            media_kind="image",
        ),
    )

    task = await message_logic.build_user_task(msg, geometry, "поясни мем")

    assert task is not None
    assert task.instruction == "поясни мем"
    assert task.has_media_target is True
    assert task.media_type == "image"
    assert task.is_instruction_on_target is True
    assert task.target_message_id == 123
    assert task.target_message_text == "це мем про змову"
    assert task.should_store_user_message is True


def test_turn_context_marks_reply_target_as_context_only():
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="count to 17",
        reply_to_bot=True,
        reply_target=ReplyTarget(
            message_id=123,
            text="old long answer about magnesium",
            is_bot=True,
        ),
    )

    context = render_turn_context_messages(geometry)[0]["content"]

    assert "current_user_text: count to 17" in context
    assert "reply_target_text: old long answer about magnesium" in context
    assert "reply_context_policy:" in context
    assert "current_user_text is the active request" in context
    assert "Do not answer reply_target_text as a second request" in context


@pytest.mark.asyncio
async def test_build_user_task_does_not_store_synthetic_media_default_prompt():
    msg = make_unified_message("")
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="",
        addressed_via_mention=True,
        addressed=True,
        target_media_kind="image",
        reply_target=ReplyTarget(
            message_id=124,
            text="мем",
            media_kind="image",
        ),
    )

    task = await message_logic.build_user_task(
        msg,
        geometry,
        "Проаналізуй наведене медіа і відповідай по суті завдання.",
    )

    assert task is not None
    assert task.should_store_user_message is False


@pytest.mark.asyncio
async def test_plan_execution_wraps_planner_decision(monkeypatch):
    def fake_plan_message(_task):
        return PlanDecision(
            route="search",
            capability="search_web",
            use_reasoning=True,
            planner_source="test_planner",
            notes="search",
        )

    monkeypatch.setattr(message_logic, "plan_message", fake_plan_message)

    task = message_logic.UserTask(
        instruction="пошукай новини про NASA",
        has_media_target=False,
        needs_search_hint=True,
    )
    geometry = MessageGeometry(chat_type="group", addressed=True)
    session = message_logic.SessionState(chat_id=99950, authed=True)

    plan = await message_logic.plan_execution(99950, task, geometry, session)

    assert plan.route == "search"
    assert plan.capability == "search_web"
    assert plan.use_reasoning is True
    assert plan.planner_source == "test_planner"


@pytest.mark.asyncio
async def test_execute_plan_routes_to_search(monkeypatch):
    called = {}

    async def fake_run_search(chat_id, user_text, **kwargs):
        called["chat_id"] = chat_id
        called["user_text"] = user_text
        called["kwargs"] = kwargs
        return "SEARCH: OK"

    monkeypatch.setattr(message_logic, "run_search", fake_run_search)

    task = message_logic.UserTask(
        instruction="пошукай новини",
        has_media_target=False,
        turn_context_msgs=[{"role": "system", "content": "[CHAT-GEOMETRY]"}],
    )
    plan = message_logic.ExecutionPlan(
        route="search",
        capability="search_web",
        use_reasoning=False,
        planner_source="test",
    )

    result = await message_logic.execute_plan(99950, task, plan)

    assert result.text == "SEARCH: OK\n\n⚠️УВАГА! ВІДБУВСЯ ПОШУК!⚠️"
    assert called["chat_id"] == 99950
    assert called["user_text"] == "пошукай новини"
    assert called["kwargs"]["turn_context_msgs"] == task.turn_context_msgs


@pytest.mark.asyncio
async def test_execute_plan_prepends_current_media_context(monkeypatch):
    called = {}

    async def fake_run_simple(chat_id, user_text, **kwargs):
        called["chat_id"] = chat_id
        called["user_text"] = user_text
        called["kwargs"] = kwargs
        return "VISION: OK"

    monkeypatch.setattr(message_logic, "run_simple", fake_run_simple)

    task = message_logic.UserTask(
        instruction="хто це?",
        has_media_target=True,
        media_type="image",
        media_context="target_media_type: photo\nmedia_analysis: поточне фото з пташками",
        turn_context_msgs=[{"role": "system", "content": "[CHAT-GEOMETRY]"}],
    )
    plan = message_logic.ExecutionPlan(
        route="image",
        capability="vision_image",
        use_reasoning=False,
        planner_source="test",
    )

    result = await message_logic.execute_plan(99950, task, plan)

    assert result.text == "VISION: OK"
    turn_context = called["kwargs"]["turn_context_msgs"]
    assert turn_context[0]["role"] == "system"
    assert turn_context[0]["content"].startswith("[MEDIA_CURRENT]")
    assert "поточне фото з пташками" in turn_context[0]["content"]
    assert turn_context[1:] == task.turn_context_msgs


@pytest.mark.asyncio
async def test_send_response_renders_telegram_html():
    msg = make_unified_message()

    await message_logic.send_response(
        msg,
        "*Оновлення:*\n\nДжерела:\n- [nasa.gov](https://www.nasa.gov/)",
    )

    sent_text = msg.raw_update.effective_message._sent[-1]
    sent_kwargs = msg.raw_update.effective_message._sent_kwargs[-1]
    assert "<b>Оновлення:</b>" in sent_text
    assert '<a href="https://www.nasa.gov/">nasa.gov</a>' in sent_text
    assert sent_kwargs["parse_mode"] == "HTML"
    assert sent_kwargs["disable_web_page_preview"] is True
