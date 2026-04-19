from types import SimpleNamespace

import pytest

import agent.planner as planner
import agent.search_task as search_task
import app.message_logic as message_logic
from adapters.base import MessageGeometry, ReplyTarget, UnifiedMessage


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
        effective_chat=SimpleNamespace(id=99970, type="group"),
        _bot=SimpleNamespace(bot=SimpleNamespace(id=42, username=bot_username)),
    )
    return UnifiedMessage(
        platform="ptb",
        chat_id=99970,
        message_id=177,
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
async def test_build_user_task_adds_participant_history_context(monkeypatch):
    async def fake_fetch_recent(_chat_id, limit=None):
        del limit
        return [
            {
                "role": "system",
                "content": (
                    "[CHAT-TURN]\n"
                    "sender: Микита Загамула @AgNike\n"
                    "current_message_time_local: 2026-04-08 23:58:00 EEST\n"
                    "current_user_text: перша репліка"
                ),
            },
            {
                "role": "system",
                "content": (
                    "[CHAT-TURN]\n"
                    "sender: Інший Користувач @other\n"
                    "current_message_time_local: 2026-04-08 23:59:00 EEST\n"
                    "current_user_text: чужа репліка"
                ),
            },
            {
                "role": "system",
                "content": (
                    "[CHAT-TURN]\n"
                    "sender: Микита Загамула @AgNike\n"
                    "current_message_time_local: 2026-04-09 00:10:00 EEST\n"
                    "resolved_instruction: загугли це"
                ),
            },
        ]

    monkeypatch.setattr(message_logic, "fetch_recent", fake_fetch_recent)

    msg = make_unified_message("@botx Як тобі ця новина?")
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="Як тобі ця новина?",
        addressed_via_mention=True,
        addressed=True,
        message_sent_at_local="2026-04-09 00:18:02 EEST",
        message_sent_at_utc="2026-04-08T21:18:02Z",
        sender=SimpleNamespace(
            user_id=1,
            username="AgNike",
            display_name="Микита Загамула",
        ),
        reply_target=ReplyTarget(
            message_id=500,
            text="пост",
            media_kind="video",
            author=SimpleNamespace(
                user_id=2,
                username="other",
                display_name="Інший Користувач",
            ),
        ),
        target_media_kind="video",
    )

    task = await message_logic.build_user_task(msg, geometry, None)

    assert task is not None
    history_blocks = [
        item["content"]
        for item in task.turn_context_msgs
        if item["content"].startswith("[PARTICIPANT-HISTORY]")
    ]
    assert len(history_blocks) == 1
    block = history_blocks[0]
    assert "current_sender: Микита Загамула @AgNike" in block
    assert "перша репліка" in block
    assert "загугли це" in block
    assert "чужа репліка" not in block


@pytest.mark.asyncio
async def test_build_user_task_adds_thread_history_context(monkeypatch):
    async def fake_fetch_recent(_chat_id, limit=None):
        del limit
        return [
            {
                "role": "system",
                "content": (
                    "[CHAT-TURN]\n"
                    "current_message_id: 190\n"
                    "sender: Микита Загамула @AgNike\n"
                    "current_message_time_local: 2026-04-09 00:18:00 EEST\n"
                    "reply_target_message_id: 180\n"
                    "reply_target_text: пост з відео\n"
                    "current_user_text: Як тобі ця новина?"
                ),
            },
            {
                "role": "assistant",
                "content": "Схоже на велику ескалацію.",
            },
            {
                "role": "system",
                "content": (
                    "[CHAT-TURN]\n"
                    "current_message_id: 333\n"
                    "sender: Інший Користувач @other\n"
                    "current_message_time_local: 2026-04-09 00:19:00 EEST\n"
                    "reply_target_message_id: 900\n"
                    "reply_target_text: чужий пост\n"
                    "current_user_text: геть інша тема"
                ),
            },
            {
                "role": "assistant",
                "content": "Це непов’язана гілка.",
            },
        ]

    monkeypatch.setattr(message_logic, "fetch_recent", fake_fetch_recent)

    msg = make_unified_message("@botx Загугли цю новину")
    geometry = MessageGeometry(
        chat_type="group",
        current_message_id=410,
        clean_text="Загугли цю новину",
        addressed_via_mention=True,
        addressed=True,
        message_sent_at_local="2026-04-09 00:20:00 EEST",
        message_sent_at_utc="2026-04-08T21:20:00Z",
        sender=SimpleNamespace(
            user_id=1,
            username="AgNike",
            display_name="Микита Загамула",
        ),
        reply_target=ReplyTarget(
            message_id=200,
            text="відповідь бота",
            author=SimpleNamespace(
                user_id=42,
                username="botx",
                display_name="Bot",
            ),
        ),
        reply_chain=(
            ReplyTarget(
                message_id=200,
                text="відповідь бота",
                author=SimpleNamespace(
                    user_id=42,
                    username="botx",
                    display_name="Bot",
                ),
            ),
            ReplyTarget(
                message_id=180,
                text="пост з відео",
                media_kind="video",
                author=SimpleNamespace(
                    user_id=2,
                    username="other",
                    display_name="Інший Користувач",
                ),
            ),
        ),
        target_media_kind="video",
    )

    task = await message_logic.build_user_task(msg, geometry, None)

    assert task is not None
    thread_blocks = [
        item["content"]
        for item in task.turn_context_msgs
        if item["content"].startswith("[THREAD-HISTORY]")
    ]
    assert len(thread_blocks) == 1
    block = thread_blocks[0]
    assert "thread_anchor_message_ids: 180, 200, 410" in block
    assert "match=reply_chain_overlap" in block
    assert "Як тобі ця новина?" in block
    assert "Схоже на велику ескалацію." in block
    assert "геть інша тема" not in block


def test_planner_excerpt_keeps_participant_history():
    excerpt = planner._format_dialogue_excerpt(
        (
            {
                "role": "system",
                "content": (
                    "[PARTICIPANT-HISTORY]\n"
                    "current_sender: Микита Загамула @AgNike\n"
                    "recent_same_sender_turns:\n"
                    "- 2026-04-09 00:10:00 EEST | загугли це"
                ),
            },
            {"role": "user", "content": "ну загугли"},
        )
    )

    assert "[PARTICIPANT-HISTORY]" in excerpt
    assert "загугли це" in excerpt


def test_planner_excerpt_keeps_thread_history():
    excerpt = planner._format_dialogue_excerpt(
        (
            {
                "role": "system",
                "content": (
                    "[THREAD-HISTORY]\n"
                    "thread_anchor_message_ids: 180, 200\n"
                    "recent_thread_turns:\n"
                    "- 2026-04-09 00:18:00 EEST | match=reply_chain_overlap | sender: Микита Загамула @AgNike\n"
                    "  user: Як тобі ця новина?"
                ),
            },
            {"role": "user", "content": "ну загугли"},
        )
    )

    assert "[THREAD-HISTORY]" in excerpt
    assert "Як тобі ця новина?" in excerpt


def test_search_context_excerpt_keeps_participant_history():
    excerpt = search_task._context_excerpt(
        [
            {
                "role": "system",
                "content": (
                    "[PARTICIPANT-HISTORY]\n"
                    "current_sender: Микита Загамула @AgNike\n"
                    "recent_same_sender_turns:\n"
                    "- 2026-04-09 00:10:00 EEST | загугли це"
                ),
            },
            {"role": "user", "content": "ну загугли"},
        ]
    )

    assert "[PARTICIPANT-HISTORY]" in excerpt
    assert "загугли це" in excerpt


def test_search_context_excerpt_keeps_thread_history():
    excerpt = search_task._context_excerpt(
        [
            {
                "role": "system",
                "content": (
                    "[THREAD-HISTORY]\n"
                    "thread_anchor_message_ids: 180, 200\n"
                    "recent_thread_turns:\n"
                    "- 2026-04-09 00:18:00 EEST | match=reply_chain_overlap | sender: Микита Загамула @AgNike\n"
                    "  user: Як тобі ця новина?"
                ),
            },
            {"role": "user", "content": "ну загугли"},
        ]
    )

    assert "[THREAD-HISTORY]" in excerpt
    assert "Як тобі ця новина?" in excerpt
