from types import SimpleNamespace

from adapters.base import UnifiedMessage
from media import album_registry


def _make_ptb_unified(message_id: int, media_group_id: str, *, has_photo=False, has_video=False):
    raw_message = SimpleNamespace(
        message_id=message_id,
        chat_id=777,
        media_group_id=media_group_id,
        text=None,
        caption="caption" if message_id == 1 else None,
    )
    update = SimpleNamespace(effective_message=raw_message)
    return UnifiedMessage(
        platform="ptb",
        chat_id=777,
        message_id=message_id,
        text="",
        caption="caption" if message_id == 1 else None,
        reply_to_message_id=None,
        has_photo=has_photo,
        has_voice=False,
        has_video=has_video,
        has_document=False,
        raw_update=update,
        media_group_id=media_group_id,
        bot_username="botx",
    )


def test_observe_album_message_collects_items_in_order():
    album_registry._ALBUMS.clear()
    album_registry._MESSAGE_INDEX.clear()
    album_registry._PROCESSING.clear()
    album_registry._HANDLED.clear()

    msg2 = _make_ptb_unified(2, "album-42", has_video=True)
    msg1 = _make_ptb_unified(1, "album-42", has_photo=True)

    album_registry.observe_album_message(msg2)
    album_registry.observe_album_message(msg1)

    target = msg1.raw_update.effective_message
    messages = album_registry.get_ptb_album_messages(target)

    assert [message.message_id for message in messages] == [1, 2]


def test_observe_album_message_ignores_non_album_messages():
    album_registry._ALBUMS.clear()
    album_registry._MESSAGE_INDEX.clear()
    album_registry._PROCESSING.clear()
    album_registry._HANDLED.clear()

    raw_message = SimpleNamespace(message_id=10, chat_id=777, media_group_id=None)
    update = SimpleNamespace(effective_message=raw_message)
    msg = UnifiedMessage(
        platform="ptb",
        chat_id=777,
        message_id=10,
        text="",
        caption=None,
        reply_to_message_id=None,
        has_photo=True,
        has_voice=False,
        has_video=False,
        has_document=False,
        raw_update=update,
        media_group_id=None,
        bot_username="botx",
    )

    album_registry.observe_album_message(msg)

    assert album_registry.get_ptb_album_messages(raw_message) == []


def test_claim_album_processing_allows_single_claimant_until_finished():
    album_registry._ALBUMS.clear()
    album_registry._MESSAGE_INDEX.clear()
    album_registry._PROCESSING.clear()
    album_registry._HANDLED.clear()

    msg1 = _make_ptb_unified(1, "album-77", has_photo=True)
    msg2 = _make_ptb_unified(2, "album-77", has_photo=True)

    album_registry.observe_album_message(msg1)
    album_registry.observe_album_message(msg2)

    assert album_registry.claim_album_processing(msg1) is True
    assert album_registry.claim_album_processing(msg2) is False

    album_registry.finish_album_processing(msg1, handled=True)

    assert album_registry.claim_album_processing(msg2) is False
