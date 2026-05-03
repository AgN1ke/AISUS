"""Acceptance tests for category C — albums (B-024 .. B-027).

Album claim/settle/finish logic from media/album_registry.
"""
from __future__ import annotations

import pytest

from media.album_registry import (
    _album_items_for,
    claim_album_processing,
    finish_album_processing,
    observe_album_message,
)
from adapters.base import UnifiedMessage


def _make_msg(message_id: int, group_id: str, caption: str = "") -> UnifiedMessage:
    return UnifiedMessage(
        platform="ptb",
        chat_id=12345,
        message_id=message_id,
        text="",
        caption=caption or None,
        reply_to_message_id=None,
        has_photo=True,
        has_voice=False,
        has_video=False,
        has_document=False,
        raw_update=type("U", (), {"effective_message": object()})(),
        media_group_id=group_id,
    )


# ===== B-024: only first item claims, others are duplicates =====

def test_B024_only_one_item_claims_album():
    """B-024: 3 photos same group_id → only first claim() returns True."""
    group = "test-group-1"
    msg1 = _make_msg(101, group, "@saintaibot опиши")
    msg2 = _make_msg(102, group)
    msg3 = _make_msg(103, group)

    observe_album_message(msg1)
    observe_album_message(msg2)
    observe_album_message(msg3)

    assert claim_album_processing(msg1) is True
    assert claim_album_processing(msg2) is False
    assert claim_album_processing(msg3) is False


# ===== B-025: caption can live on any item, all visible via _album_items_for =====

def test_B025_caption_on_any_item_visible_in_album():
    """B-025: меншн на третьому елементі альбому — все одно видно."""
    group = "test-group-2"
    msg1 = _make_msg(201, group)  # no caption
    msg2 = _make_msg(202, group)  # no caption
    msg3 = _make_msg(203, group, "@saintaibot опиши")

    observe_album_message(msg1)
    observe_album_message(msg2)
    observe_album_message(msg3)

    items = _album_items_for("ptb", 12345, group)
    captions = [(it.text or "").strip() for it in items if (it.text or "").strip()]
    assert any("@saintaibot" in c for c in captions)


# ===== B-024 cleanup: finish_album_processing releases claim =====

def test_B024_finish_marks_album_handled():
    """After finish(handled=True), subsequent claims for same group are blocked."""
    group = "test-group-3"
    msg1 = _make_msg(301, group, "@saintaibot")
    msg2 = _make_msg(302, group)

    observe_album_message(msg1)
    observe_album_message(msg2)

    assert claim_album_processing(msg1) is True
    finish_album_processing(msg1, handled=True)
    # New claim attempt for sibling should fail (already handled)
    assert claim_album_processing(msg2) is False


# ===== B-026: album bundle composition shows ALL items in [MEDIA] block =====


def test_B026_album_bundle_includes_every_item():
    """B-026: _compose_album_bundle renders ALL items as album_item_N_*.

    Previously bot saw only first item. Now LLM gets `album_item_count`,
    `album_item_1_type`, ..., `album_item_N_type`, plus per-item analysis.
    """
    from media.router import _compose_album_bundle

    items = [
        {"type": "photo", "message_id": 1, "text": "перше фото", "analysis": "опис фото 1", "transcript": ""},
        {"type": "photo", "message_id": 2, "text": "", "analysis": "опис фото 2", "transcript": ""},
        {"type": "video", "message_id": 3, "text": "", "analysis": "відео-кадри", "transcript": "пррр"},
    ]
    bundle = _compose_album_bundle(
        post_text="@saintaibot опиши все",
        route_kind="video",
        group_id="g123",
        items=items,
    )
    assert "target_media_type: album" in bundle
    assert "album_item_count: 3" in bundle
    assert "album_route_media_kind: video" in bundle
    assert "album_item_1_type: photo" in bundle
    assert "album_item_2_type: photo" in bundle
    assert "album_item_3_type: video" in bundle
    assert "опис фото 1" in bundle
    assert "опис фото 2" in bundle
    assert "відео-кадри" in bundle
    assert "пррр" in bundle  # transcript present


def test_B026_mixed_album_route_kind_is_video():
    """B-026: mixed photo+video album → route_kind='video' (Gemini handles all)."""
    from media.downloader import _album_route_kind

    items_mixed = [
        {"type": "photo", "paths": ["/tmp/p.jpg"]},
        {"type": "video", "paths": ["/tmp/v.mp4"]},
        {"type": "photo", "paths": ["/tmp/p2.jpg"]},
    ]
    items_photos_only = [
        {"type": "photo", "paths": ["/tmp/p1.jpg"]},
        {"type": "photo", "paths": ["/tmp/p2.jpg"]},
    ]
    assert _album_route_kind(items_mixed) == "video"
    assert _album_route_kind(items_photos_only) == "image"


# ===== B-026 (continued): per-item error handling — bad item doesn't kill album =====


@pytest.mark.asyncio
async def test_B026_one_broken_item_does_not_kill_album(monkeypatch):
    """B-026: якщо 1 item альбому має error_reason — bundle все одно має решту items.

    Раніше один зламаний айтем валив весь альбом. Тепер `_build_media_context`
    обгорнуто try/except per item; помилка йде в `analysis` цього айтема,
    решта йдуть нормально.
    """
    from media.router import _build_media_context

    # Stub vision/video so we don't hit network
    monkeypatch.setattr(
        "media.router.describe_images",
        lambda paths, task_hint=None: "опис двох фото",
    )

    info = {
        "type": "album",
        "group_id": "g42",
        "route_kind": "image",
        "items": [
            {"type": "photo", "message_id": 1, "paths": ["/tmp/ok.jpg"], "text": ""},
            {
                "type": "photo",
                "message_id": 2,
                "paths": [],  # empty paths
                "text": "",
                "error_reason": "Не вдалося завантажити photo: file too big",
            },
            {"type": "photo", "message_id": 3, "paths": ["/tmp/ok2.jpg"], "text": ""},
        ],
        "paths": ["/tmp/ok.jpg", "/tmp/ok2.jpg"],
        "text": "",
    }

    async def _on_error(_text):
        return None

    bundle, semantic_text = await _build_media_context(info, "опиши", _on_error)
    assert "target_media_type: album" in bundle
    assert "album_item_count: 3" in bundle
    assert "file too big" in bundle  # broken item's error injected as analysis
    assert "опис двох фото" in bundle  # other items still processed


# ===== B-027: reply на album → handle_ptb_mention бере всі sibling-items =====


def test_B027_album_messages_lookup_returns_all_siblings():
    """B-027: get_ptb_album_messages знаходить всі sibling-items по media_group_id."""
    from media.album_registry import get_ptb_album_messages

    # Sentinel raw messages — get_ptb_album_messages returns them as-is.
    group = "lookup-test-group"
    fake_raw_1 = type("M", (), {"id": 1})()
    fake_raw_2 = type("M", (), {"id": 2})()

    msg1 = _make_msg(401, group, "@saintaibot опиши")
    msg2 = _make_msg(402, group)
    # observe_album_message stores msg.raw_update.effective_message;
    # build raw_update for these:
    msg1.raw_update = type("U", (), {"effective_message": fake_raw_1})()
    msg2.raw_update = type("U", (), {"effective_message": fake_raw_2})()

    observe_album_message(msg1)
    observe_album_message(msg2)

    # Lookup by sentinel with media_group_id+chat_id
    sentinel = type(
        "M", (), {"media_group_id": group, "chat_id": 12345}
    )()
    found = get_ptb_album_messages(sentinel)
    assert len(found) == 2
    assert fake_raw_1 in found
    assert fake_raw_2 in found
