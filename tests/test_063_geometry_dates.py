import app.message_logic as message_logic
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from adapters.base import MessageGeometry, ReplyTarget
from app.chat_geometry import render_turn_context_messages, resolve_message_geometry


def test_render_turn_context_messages_includes_message_times():
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="Що це було?",
        addressed_via_mention=True,
        addressed=True,
        message_sent_at_local="2026-04-09 00:20:53 EEST",
        message_sent_at_utc="2026-04-08T21:20:53Z",
        reply_target=ReplyTarget(
            message_id=321,
            text="пост із новиною",
            media_kind="video",
            sent_at_local="2026-04-09 00:18:02 EEST",
            sent_at_utc="2026-04-08T21:18:02Z",
        ),
    )

    messages = render_turn_context_messages(geometry)

    assert len(messages) == 1
    content = messages[0]["content"]
    assert "current_message_time_local: 2026-04-09 00:20:53 EEST" in content
    assert "current_message_time_utc: 2026-04-08T21:20:53Z" in content
    assert "reply_target_time_local: 2026-04-09 00:18:02 EEST" in content
    assert "reply_target_time_utc: 2026-04-08T21:18:02Z" in content


def test_build_chat_turn_memory_event_includes_message_times():
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="Загугли цю новину",
        addressed_via_mention=True,
        addressed=True,
        message_sent_at_local="2026-04-09 00:20:53 EEST",
        message_sent_at_utc="2026-04-08T21:20:53Z",
        reply_target=ReplyTarget(
            message_id=555,
            text="Масовані удари в Бейруті",
            media_kind="video",
            sent_at_local="2026-04-09 00:18:02 EEST",
            sent_at_utc="2026-04-08T21:18:02Z",
        ),
    )
    task = message_logic.UserTask(
        instruction="Загугли цю новину",
        has_media_target=True,
        media_type="video",
        target_message_id=555,
        target_message_text="Масовані удари в Бейруті",
    )

    event = message_logic._build_chat_turn_memory_event(geometry, task)

    assert "current_message_time_local: 2026-04-09 00:20:53 EEST" in event
    assert "reply_target_time_local: 2026-04-09 00:18:02 EEST" in event


def test_resolve_message_geometry_reads_ptb_message_dates():
    reply = SimpleNamespace(
        message_id=88,
        text="первинний пост",
        caption=None,
        from_user=SimpleNamespace(id=7, username="oleg", first_name="Олег", last_name=""),
        photo=[],
        voice=None,
        video=None,
        document=None,
        audio=None,
        date=datetime(2026, 4, 8, 21, 18, 2, tzinfo=timezone.utc),
    )
    message = SimpleNamespace(
        message_id=99,
        text="@botx Загугли цю новину",
        caption=None,
        from_user=SimpleNamespace(id=42, username="mikita", first_name="Микита", last_name=""),
        reply_to_message=reply,
        entities=[],
        caption_entities=[],
        photo=[],
        voice=None,
        video=None,
        document=None,
        audio=None,
        date=datetime(2026, 4, 8, 21, 20, 53, tzinfo=timezone.utc),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(type="group"),
        _bot=SimpleNamespace(bot=SimpleNamespace(id=123, username="botx")),
    )
    unified = SimpleNamespace(platform="ptb", raw_update=update, bot_username="botx")

    geometry = asyncio.run(resolve_message_geometry(unified))

    assert geometry.message_sent_at_utc == "2026-04-08T21:20:53Z"
    assert geometry.reply_target.sent_at_utc == "2026-04-08T21:18:02Z"
    assert geometry.message_sent_at_local is not None
    assert geometry.reply_target.sent_at_local is not None


def test_resolve_message_geometry_treats_video_note_as_video():
    reply = SimpleNamespace(
        message_id=201,
        text="кружечок із новиною",
        caption=None,
        from_user=SimpleNamespace(id=7, username="oleg", first_name="Олег", last_name=""),
        photo=[],
        voice=None,
        video=None,
        video_note=SimpleNamespace(file_id="reply-circle"),
        document=None,
        audio=None,
        date=datetime(2026, 4, 9, 9, 0, 0, tzinfo=timezone.utc),
    )
    message = SimpleNamespace(
        message_id=202,
        text="@botx що на кружечку?",
        caption=None,
        from_user=SimpleNamespace(id=42, username="mikita", first_name="Микита", last_name=""),
        reply_to_message=reply,
        entities=[],
        caption_entities=[],
        photo=[],
        voice=None,
        video=None,
        video_note=None,
        document=None,
        audio=None,
        date=datetime(2026, 4, 9, 9, 1, 0, tzinfo=timezone.utc),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(type="group"),
        _bot=SimpleNamespace(bot=SimpleNamespace(id=123, username="botx")),
    )
    unified = SimpleNamespace(platform="ptb", raw_update=update, bot_username="botx")

    geometry = asyncio.run(resolve_message_geometry(unified))

    assert geometry.target_media_kind == "video"
    assert geometry.reply_target.media_kind == "video"


def test_resolve_message_geometry_accepts_text_mention_for_bot():
    message = SimpleNamespace(
        message_id=303,
        text="бот, відгукнись",
        caption=None,
        from_user=SimpleNamespace(id=42, username="mikita", first_name="Микита", last_name=""),
        reply_to_message=None,
        entities=[
            SimpleNamespace(
                type="text_mention",
                user=SimpleNamespace(id=123, username="botx"),
            )
        ],
        caption_entities=[],
        photo=[],
        voice=None,
        video=None,
        video_note=None,
        document=None,
        audio=None,
        date=datetime(2026, 4, 9, 10, 1, 0, tzinfo=timezone.utc),
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(type="group"),
        _bot=SimpleNamespace(bot=SimpleNamespace(id=123, username="botx")),
    )
    unified = SimpleNamespace(platform="ptb", raw_update=update, bot_username="botx")

    geometry = asyncio.run(resolve_message_geometry(unified))

    assert geometry.addressed_via_mention is True
    assert geometry.addressed is True
