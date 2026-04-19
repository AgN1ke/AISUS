from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from adapters.base import UnifiedMessage

ALBUM_REGISTRY_TTL_SECONDS = int(os.getenv("ALBUM_REGISTRY_TTL_SECONDS", "3600"))
ALBUM_REGISTRY_MAX_GROUPS = int(os.getenv("ALBUM_REGISTRY_MAX_GROUPS", "500"))
ALBUM_PROCESSING_SETTLE_SECONDS = float(
    os.getenv("ALBUM_PROCESSING_SETTLE_SECONDS", "1.2")
)
ALBUM_PROCESSING_TTL_SECONDS = int(
    os.getenv("ALBUM_PROCESSING_TTL_SECONDS", "120")
)


@dataclass
class AlbumItemRef:
    message_id: int
    media_kind: str
    raw_message: Any
    text: str = ""
    created_at: float = field(default_factory=time.time)


_LOCK = threading.Lock()
_ALBUMS: dict[tuple[str, int, str], list[AlbumItemRef]] = {}
_MESSAGE_INDEX: dict[tuple[str, int, int], tuple[str, int, str]] = {}
_PROCESSING: dict[tuple[str, int, str], tuple[int, float]] = {}
_HANDLED: dict[tuple[str, int, str], float] = {}


def _now() -> float:
    return time.time()


def _purge_locked(now: float | None = None) -> None:
    current = now if now is not None else _now()
    stale_album_keys = []
    for key, items in list(_ALBUMS.items()):
        fresh_items = [
            item for item in items if current - float(item.created_at or current) <= ALBUM_REGISTRY_TTL_SECONDS
        ]
        if fresh_items:
            _ALBUMS[key] = fresh_items[-20:]
            continue
        stale_album_keys.append(key)

    for key in stale_album_keys:
        _ALBUMS.pop(key, None)

    stale_message_keys = []
    for message_key, album_key in list(_MESSAGE_INDEX.items()):
        if album_key not in _ALBUMS:
            stale_message_keys.append(message_key)
    for key in stale_message_keys:
        _MESSAGE_INDEX.pop(key, None)

    stale_processing_keys = []
    for album_key, (_message_id, started_at) in list(_PROCESSING.items()):
        if album_key not in _ALBUMS or current - started_at > ALBUM_PROCESSING_TTL_SECONDS:
            stale_processing_keys.append(album_key)
    for key in stale_processing_keys:
        _PROCESSING.pop(key, None)

    stale_handled_keys = []
    for album_key, handled_at in list(_HANDLED.items()):
        if album_key not in _ALBUMS or current - handled_at > ALBUM_PROCESSING_TTL_SECONDS:
            stale_handled_keys.append(album_key)
    for key in stale_handled_keys:
        _HANDLED.pop(key, None)

    if len(_ALBUMS) <= ALBUM_REGISTRY_MAX_GROUPS:
        return

    sorted_groups = sorted(
        _ALBUMS.items(),
        key=lambda pair: max((item.created_at for item in pair[1]), default=0.0),
    )
    for album_key, _items in sorted_groups[: max(0, len(_ALBUMS) - ALBUM_REGISTRY_MAX_GROUPS)]:
        _ALBUMS.pop(album_key, None)
        for message_key, indexed_album_key in list(_MESSAGE_INDEX.items()):
            if indexed_album_key == album_key:
                _MESSAGE_INDEX.pop(message_key, None)


def _infer_media_kind(msg: UnifiedMessage) -> str | None:
    if msg.has_video or msg.has_video_note:
        return "video"
    if msg.has_photo:
        return "image"
    if msg.has_voice:
        return "voice"
    if msg.has_document:
        return "document"
    return None


def observe_album_message(msg: UnifiedMessage) -> None:
    group_id = (msg.media_group_id or "").strip()
    if not group_id:
        return

    media_kind = _infer_media_kind(msg)
    if not media_kind:
        return

    if msg.platform == "ptb":
        raw_message = getattr(msg.raw_update, "effective_message", None)
    else:
        raw_message = getattr(msg.raw_update, "message", None)
    if raw_message is None:
        return

    album_key = (msg.platform, int(msg.chat_id), group_id)
    message_key = (msg.platform, int(msg.chat_id), int(msg.message_id))
    item = AlbumItemRef(
        message_id=int(msg.message_id),
        media_kind=media_kind,
        raw_message=raw_message,
        text=(msg.caption or msg.text or "").strip(),
    )

    with _LOCK:
        _purge_locked()
        bucket = _ALBUMS.setdefault(album_key, [])
        replaced = False
        for index, existing in enumerate(bucket):
            if existing.message_id == item.message_id:
                bucket[index] = item
                replaced = True
                break
        if not replaced:
            bucket.append(item)
            bucket.sort(key=lambda value: value.message_id)
        _MESSAGE_INDEX[message_key] = album_key


def _album_items_for(platform: str, chat_id: int, group_id: str) -> list[AlbumItemRef]:
    with _LOCK:
        _purge_locked()
        return list(_ALBUMS.get((platform, int(chat_id), group_id), []))


def claim_album_processing(msg: UnifiedMessage) -> bool:
    group_id = (msg.media_group_id or "").strip()
    if not group_id:
        return False

    album_key = (msg.platform, int(msg.chat_id), group_id)
    with _LOCK:
        _purge_locked()
        if album_key in _HANDLED:
            return False
        existing = _PROCESSING.get(album_key)
        if existing is None:
            _PROCESSING[album_key] = (int(msg.message_id), _now())
            return True
        return existing[0] == int(msg.message_id)


def finish_album_processing(msg: UnifiedMessage, *, handled: bool) -> None:
    group_id = (msg.media_group_id or "").strip()
    if not group_id:
        return

    album_key = (msg.platform, int(msg.chat_id), group_id)
    with _LOCK:
        _purge_locked()
        existing = _PROCESSING.get(album_key)
        if existing and existing[0] == int(msg.message_id):
            _PROCESSING.pop(album_key, None)
        if handled:
            _HANDLED[album_key] = _now()


def get_ptb_album_messages(message: Any) -> list[Any]:
    if message is None:
        return []
    group_id = str(getattr(message, "media_group_id", "") or "").strip()
    if not group_id:
        return []
    chat_id = getattr(message, "chat_id", None)
    if chat_id is None:
        return []
    items = _album_items_for("ptb", int(chat_id), group_id)
    if not items:
        return []
    return [item.raw_message for item in items if item.raw_message is not None]


def get_telethon_album_messages(event: Any) -> list[Any]:
    message = getattr(event, "message", None)
    if message is None:
        return []
    group_id = str(getattr(message, "grouped_id", "") or "").strip()
    if not group_id:
        return []
    chat_id = getattr(event, "chat_id", None)
    if chat_id is None:
        return []
    items = _album_items_for("telethon", int(chat_id), group_id)
    if not items:
        return []
    return [item.raw_message for item in items if item.raw_message is not None]
