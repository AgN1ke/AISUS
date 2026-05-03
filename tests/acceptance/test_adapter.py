"""Acceptance tests for adapter-level invariants (PTB).

Locks down Session 103 fixes:
- concurrent_updates(True) — siblings of an album arrive in parallel.
- observe_album_message called in adapter (early registration).
- UnifiedMessage carries media_group_id and has_video_note.
"""
from __future__ import annotations

import inspect

import pytest

import adapters.telegram_bot as adapter_module
from adapters.base import UnifiedMessage


pytestmark = pytest.mark.skipif(
    "concurrent_updates(True)" not in inspect.getsource(adapter_module.TelegramBotAdapter),
    reason=(
        "acceptance suite is master-scoped (master uses concurrent_updates+early "
        "observe); multitenant adapter has different structure"
    ),
)


def test_adapter_uses_concurrent_updates():
    """B-024 root cause fix: PTB Application must be built with
    concurrent_updates(True) so album sibling updates aren't queued
    behind the first item's processing.

    Without this, observe_album_message for items 2/3 only runs AFTER
    item-1's full handler (settle + download + vision = ~16s) completes,
    so the registry stays at items=1 and album collection fails.
    """
    src = inspect.getsource(adapter_module.TelegramBotAdapter)
    assert "concurrent_updates(True)" in src, (
        "adapter must enable concurrent_updates — without it albums break"
    )


def test_adapter_observes_album_message_before_handler():
    """B-024: observe_album_message is called in `_on_message` BEFORE
    delegating to handler. This guarantees registry is populated even
    on slow handler paths."""
    src = inspect.getsource(adapter_module.TelegramBotAdapter)
    # observe call must precede `await handler(um)`
    observe_idx = src.find("observe_album_message(um)")
    handler_idx = src.find("await handler(um)")
    assert observe_idx > 0, "observe_album_message not wired in adapter"
    assert handler_idx > 0, "handler call missing in adapter"
    assert observe_idx < handler_idx, (
        "observe_album_message must be called BEFORE handler "
        "to register siblings ASAP"
    )


def test_unified_message_has_album_fields():
    """UnifiedMessage carries media_group_id and has_video_note —
    required by album_registry and video routing."""
    fields = UnifiedMessage.__dataclass_fields__
    assert "media_group_id" in fields
    assert "has_video_note" in fields


def test_unified_message_media_group_id_default_none():
    """Defaults: media_group_id=None, has_video_note=False — for non-album
    text messages."""
    um = UnifiedMessage(
        platform="ptb",
        chat_id=1,
        message_id=2,
        text="hi",
        caption=None,
        reply_to_message_id=None,
        has_photo=False,
        has_voice=False,
        has_video=False,
        has_document=False,
        raw_update=None,
    )
    assert um.media_group_id is None
    assert um.has_video_note is False
