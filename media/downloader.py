from __future__ import annotations
import os, shutil
from pathlib import Path
from typing import Optional, List

MEDIA_TMP = Path(os.getenv("MEDIA_TMP_DIR", "/tmp/aisus_media"))
MEDIA_TMP.mkdir(parents=True, exist_ok=True)

# ---- PTB ----
async def download_from_ptb_message(msg, context) -> dict:
    """
    Повертає {type: 'photo'|'video'|'voice'|'audio'|'doc'|'text', 'paths': [..], 'text': str|None}
    Для photo/video бере найякіснішу версію.
    """
    res = {"type": "text", "paths": [], "text": (msg.text or msg.caption or None)}
    bot = context.bot

    if msg.photo:
        ph = msg.photo[-1]
        f = await bot.get_file(ph.file_id)
        dst = MEDIA_TMP / f"{msg.chat_id}_{msg.message_id}.jpg"
        await f.download_to_drive(custom_path=str(dst))
        res["type"] = "photo"; res["paths"] = [str(dst)]
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
    return res

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
            return res
        ext = os.path.splitext(path)[1].lower()
        res["paths"] = [path]
        if msg.photo or isinstance(msg.media, MessageMediaPhoto) or ext in (".jpg", ".jpeg", ".png", ".webp"):
            res["type"] = "photo"
        elif msg.video or ext in (".mp4", ".mov", ".mkv"):
            res["type"] = "video"
        elif ext in (".ogg", ".oga", ".opus"):
            res["type"] = "voice"
        elif ext in (".mp3", ".wav", ".m4a"):
            res["type"] = "audio"
        else:
            res["type"] = "doc"
    return res
