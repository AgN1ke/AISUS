from __future__ import annotations
import asyncio
import os, shutil, time
from pathlib import Path
from typing import Optional, List

MEDIA_TMP = Path(os.getenv("MEDIA_TMP_DIR", "/tmp/aisus_media"))
MEDIA_TMP.mkdir(parents=True, exist_ok=True)
MEDIA_TMP_MAX_AGE_HOURS = int(os.getenv("MEDIA_TMP_MAX_AGE_HOURS", "24"))


def _safe_media_path(path: str | Path) -> Path | None:
    try:
        candidate = Path(path).resolve()
        candidate.relative_to(MEDIA_TMP.resolve())
        return candidate
    except Exception:
        return None


def cleanup_downloaded_media_sync(paths: List[str]) -> None:
    seen: set[Path] = set()
    for raw_path in paths or []:
        candidate = _safe_media_path(raw_path)
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        try:
            if candidate.is_dir():
                shutil.rmtree(candidate, ignore_errors=True)
            else:
                candidate.unlink(missing_ok=True)
        except Exception:
            continue

        parent = candidate.parent
        root = MEDIA_TMP.resolve()
        while True:
            if parent == root or not str(parent).startswith(str(root)):
                break
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


async def cleanup_downloaded_media(paths: List[str]) -> None:
    await asyncio.to_thread(cleanup_downloaded_media_sync, paths)


def purge_stale_media_tmp_sync(max_age_hours: int | None = None) -> int:
    ttl_hours = max_age_hours if max_age_hours is not None else MEDIA_TMP_MAX_AGE_HOURS
    ttl_seconds = max(1, int(ttl_hours)) * 3600
    cutoff = time.time() - ttl_seconds
    removed = 0

    for path in sorted(MEDIA_TMP.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_dir():
                path.rmdir()
                continue
            if path.stat().st_mtime > cutoff:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
        except Exception:
            continue

    return removed


async def purge_stale_media_tmp(max_age_hours: int | None = None) -> int:
    return await asyncio.to_thread(purge_stale_media_tmp_sync, max_age_hours)

# ---- PTB ----
async def download_from_ptb_message(msg, context) -> dict:
    """
    Повертає {type: 'photo'|'video'|'voice'|'audio'|'doc'|'text', 'paths': [..], 'text': str|None}
    Для photo/video бере найякіснішу версію.
    If download fails (e.g. file too big), returns type with 'error' and 'error_reason' key.
    """
    res = {"type": "text", "paths": [], "text": (msg.text or msg.caption or None)}
    bot = context.bot

    try:
        if msg.photo:
            ph = msg.photo[-1]
            f = await bot.get_file(ph.file_id)
            dst = MEDIA_TMP / f"{msg.chat_id}_{msg.message_id}.jpg"
            await f.download_to_drive(custom_path=str(dst))
            res["type"] = "photo"; res["paths"] = [str(dst)]
        elif getattr(msg, "video_note", None):
            f = await bot.get_file(msg.video_note.file_id)
            dst = MEDIA_TMP / f"{msg.chat_id}_{msg.message_id}.mp4"
            await f.download_to_drive(custom_path=str(dst))
            res["type"] = "video"; res["paths"] = [str(dst)]
        elif msg.video:
            f = await bot.get_file(msg.video.file_id)
            dst = MEDIA_TMP / f"{msg.chat_id}_{msg.message_id}.mp4"
            await f.download_to_drive(custom_path=str(dst))
            res["type"] = "video"; res["paths"] = [str(dst)]
        elif msg.voice:
            f = await bot.get_file(msg.voice.file_id)
            dst = MEDIA_TMP / f"{msg.chat_id}_{msg.message_id}.ogg"
            await f.download_to_drive(custom_path=str(dst))
            res["type"] = "voice"; res["paths"] = [str(dst)]
        elif msg.audio:
            f = await bot.get_file(msg.audio.file_id)
            dst = MEDIA_TMP / f"{msg.chat_id}_{msg.message_id}.mp3"
            await f.download_to_drive(custom_path=str(dst))
            res["type"] = "audio"; res["paths"] = [str(dst)]
        elif msg.document:
            f = await bot.get_file(msg.document.file_id)
            ext = os.path.splitext(msg.document.file_name or "file.bin")[1] or ".bin"
            dst = MEDIA_TMP / f"{msg.chat_id}_{msg.message_id}{ext}"
            await f.download_to_drive(custom_path=str(dst))
            res["type"] = "doc"; res["paths"] = [str(dst)]
        else:
            res["type"] = "text"
    except Exception as exc:
        media_kind = (
            "video" if (msg.video or getattr(msg, "video_note", None))
            else "photo" if msg.photo
            else "voice" if msg.voice
            else "audio" if msg.audio
            else "document" if msg.document
            else "media"
        )
        res["type"] = media_kind
        res["paths"] = []
        res["error"] = True
        res["error_reason"] = f"Не вдалося завантажити {media_kind}: {exc}"
    return res


def _album_post_text(items: List[dict]) -> str:
    seen: set[str] = set()
    texts: list[str] = []
    for item in items:
        value = str(item.get("text") or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        texts.append(value)
    return "\n\n".join(texts).strip()


def _album_route_kind(items: List[dict]) -> str | None:
    types = [(item.get("type") or "").strip().lower() for item in items]
    if any(value == "video" for value in types):
        return "video"
    if any(value == "photo" for value in types):
        return "image"
    if any(value in {"voice", "audio"} for value in types):
        return "voice"
    if any(value == "doc" for value in types):
        return "document"
    return None


async def download_from_ptb_album(messages, context) -> dict:
    ordered_messages = sorted(
        [message for message in (messages or []) if message is not None],
        key=lambda value: getattr(value, "message_id", 0),
    )
    items: List[dict] = []
    all_paths: List[str] = []
    group_id = ""
    for message in ordered_messages:
        group_id = group_id or str(getattr(message, "media_group_id", "") or "").strip()
        item = await download_from_ptb_message(message, context)
        if (item.get("type") or "").strip().lower() == "text":
            continue
        item["message_id"] = getattr(message, "message_id", None)
        items.append(item)
        all_paths.extend(item.get("paths") or [])
    return {
        "type": "album",
        "group_id": group_id or None,
        "route_kind": _album_route_kind(items),
        "items": items,
        "paths": all_paths,
        "text": _album_post_text(items),
    }

# ---- Telethon ----
async def download_from_telethon_message(event) -> dict:
    """
    Аналогічно PTB, але через Telethon:
    """
    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
    msg = event.message
    res = {"type": "text", "paths": [], "text": (msg.message or None)}

    if msg.media:
        dst = MEDIA_TMP / f"{event.chat_id}_{msg.id}"
        dst_parent = dst
        dst_parent.mkdir(parents=True, exist_ok=True)
        path = await event.client.download_media(message=msg, file=str(dst_parent))
        if not path:
            shutil.rmtree(dst_parent, ignore_errors=True)
            return res
        ext = os.path.splitext(path)[1].lower()
        res["paths"] = [path]
        if msg.photo or isinstance(msg.media, MessageMediaPhoto) or ext in (".jpg", ".jpeg", ".png", ".webp"):
            res["type"] = "photo"
        elif (
            msg.video
            or getattr(msg, "video_note", None)
            or getattr(msg, "round", None)
            or ext in (".mp4", ".mov", ".mkv")
        ):
            res["type"] = "video"
        elif ext in (".ogg", ".oga", ".opus"):
            res["type"] = "voice"
        elif ext in (".mp3", ".wav", ".m4a"):
            res["type"] = "audio"
        else:
            res["type"] = "doc"
    return res


async def download_from_telethon_album(events) -> dict:
    ordered_events = sorted(
        [event for event in (events or []) if event is not None],
        key=lambda value: getattr(getattr(value, "message", None), "id", 0),
    )
    items: List[dict] = []
    all_paths: List[str] = []
    group_id = ""
    for event in ordered_events:
        message = getattr(event, "message", None)
        group_id = group_id or str(getattr(message, "grouped_id", "") or "").strip()
        item = await download_from_telethon_message(event)
        if (item.get("type") or "").strip().lower() == "text":
            continue
        item["message_id"] = getattr(message, "id", None)
        items.append(item)
        all_paths.extend(item.get("paths") or [])
    return {
        "type": "album",
        "group_id": group_id or None,
        "route_kind": _album_route_kind(items),
        "items": items,
        "paths": all_paths,
        "text": _album_post_text(items),
    }
