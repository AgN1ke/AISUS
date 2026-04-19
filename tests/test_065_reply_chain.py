import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import app.message_logic as message_logic
from adapters.base import MessageGeometry, ReplyTarget
from app.chat_geometry import render_turn_context_messages, resolve_message_geometry


def test_render_turn_context_messages_includes_reply_chain_hops():
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="А що було перед цим?",
        addressed_via_mention=True,
        addressed=True,
        reply_target=ReplyTarget(
            message_id=200,
            text="пряма відповідь бота",
            sent_at_local="2026-04-09 15:01:00 EEST",
            sent_at_utc="2026-04-09T12:01:00Z",
        ),
        reply_chain=(
            ReplyTarget(
                message_id=200,
                text="пряма відповідь бота",
                sent_at_local="2026-04-09 15:01:00 EEST",
                sent_at_utc="2026-04-09T12:01:00Z",
            ),
            ReplyTarget(
                message_id=180,
                text="початковий пост з відео",
                media_kind="video",
                author=SimpleNamespace(
                    user_id=7,
                    username="agnike",
                    display_name="Микита Загамула",
                ),
                sent_at_local="2026-04-09 14:58:00 EEST",
                sent_at_utc="2026-04-09T11:58:00Z",
            ),
        ),
    )

    content = render_turn_context_messages(geometry)[0]["content"]

    assert "reply_chain_depth: 2" in content
    assert "reply_chain_hop_2_message_id: 180" in content
    assert "reply_chain_hop_2_author: Микита Загамула @agnike" in content
    assert "reply_chain_hop_2_media_kind: video" in content
    assert "reply_chain_hop_2_text: початковий пост з відео" in content


def test_build_chat_turn_memory_event_includes_reply_chain_hops():
    geometry = MessageGeometry(
        chat_type="group",
        clean_text="А що було перед цим?",
        addressed_via_mention=True,
        addressed=True,
        reply_target=ReplyTarget(
            message_id=200,
            text="пряма відповідь бота",
        ),
        reply_chain=(
            ReplyTarget(message_id=200, text="пряма відповідь бота"),
            ReplyTarget(
                message_id=180,
                text="початковий пост з відео",
                media_kind="video",
                author=SimpleNamespace(
                    user_id=7,
                    username="agnike",
                    display_name="Микита Загамула",
                ),
            ),
        ),
    )
    task = message_logic.UserTask(
        instruction="А що було перед цим?",
        has_media_target=False,
        target_message_id=200,
        target_message_text="пряма відповідь бота",
    )

    event = message_logic._build_chat_turn_memory_event(geometry, task)

    assert "reply_chain_depth: 2" in event
    assert "reply_chain_hop_2_message_id: 180" in event
    assert "reply_chain_hop_2_author: Микита Загамула @agnike" in event


def test_resolve_message_geometry_reads_nested_ptb_reply_chain():
    root = SimpleNamespace(
        message_id=177,
        text="первинний пост з відео",
        caption=None,
        from_user=SimpleNamespace(
            id=7,
            username="agnike",
            first_name="Микита",
            last_name="Загамула",
        ),
        photo=[],
        voice=None,
        video=object(),
        document=None,
        audio=None,
        reply_to_message=None,
        date=datetime(2026, 4, 9, 11, 58, 0, tzinfo=timezone.utc),
    )
    middle = SimpleNamespace(
        message_id=188,
        text="відповідь бота на пост",
        caption=None,
        from_user=SimpleNamespace(id=42, username="botx"),
        photo=[],
        voice=None,
        video=None,
        document=None,
        audio=None,
        reply_to_message=root,
        date=datetime(2026, 4, 9, 12, 1, 0, tzinfo=timezone.utc),
    )
    current = SimpleNamespace(
        message_id=199,
        text="@botx а що було перед цим?",
        caption=None,
        from_user=SimpleNamespace(
            id=9,
            username="eugen",
            first_name="Євген",
            last_name="Іванов",
        ),
        reply_to_message=middle,
        entities=[],
        caption_entities=[],
        photo=[],
        voice=None,
        video=None,
        document=None,
        audio=None,
        date=datetime(2026, 4, 9, 12, 2, 0, tzinfo=timezone.utc),
    )
    update = SimpleNamespace(
        effective_message=current,
        effective_chat=SimpleNamespace(type="group"),
        _bot=SimpleNamespace(bot=SimpleNamespace(id=42, username="botx")),
    )
    unified = SimpleNamespace(platform="ptb", raw_update=update, bot_username="botx")

    geometry = asyncio.run(resolve_message_geometry(unified))

    assert geometry.reply_target.message_id == 188
    assert len(geometry.reply_chain) == 2
    assert geometry.reply_chain[0].message_id == 188
    assert geometry.reply_chain[1].message_id == 177
    assert geometry.reply_chain[1].author.display_name == "Микита Загамула"
    assert geometry.reply_chain[1].media_kind == "video"
