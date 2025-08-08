from __future__ import annotations
import logging, os, re
from typing import Optional, Tuple
from media.downloader import download_from_ptb_message, download_from_telethon_message
from media.vision import describe_images
from media.video import analyze_video
from whisper_tool import transcribe as whisper_transcribe
from memory import memory_manager

logger = logging.getLogger(__name__)

def _strip_bot_mention(text: str, bot_username: Optional[str]) -> str:
    if not text:
        return ""
    t = text.strip()
    if bot_username:
        t = re.sub(rf"@{re.escape(bot_username)}\b", "", t, flags=re.I).strip()
    return t

async def handle_ptb_mention(update, context, bot_username: str) -> Optional[str]:
    msg = update.effective_message
    chat_id = update.effective_chat.id

    user_text = (msg.text or msg.caption or "") or ""
    user_text = _strip_bot_mention(user_text, bot_username)

    target = msg.reply_to_message or msg

    info = await download_from_ptb_message(target, context)
    media_context = ""
    if info["type"] == "photo":
        media_context = describe_images(info["paths"], task_hint=user_text or None)
    elif info["type"] == "video":
        try:
            media_context = analyze_video(info["paths"][0], task_hint=user_text or None)["summary"]
        except Exception as e:
            logger.error("video analysis failed: %s", e, exc_info=True)
            await msg.reply_text(str(e))
            return None
    elif info["type"] in ("voice", "audio"):
        path = info["paths"][0]
        try:
            whisper_transcribe(path)
            from pathlib import Path
            txt = Path(path).with_suffix(".txt")
            media_context = f"Транскрипт аудіо:\n{txt.read_text(encoding='utf-8') if txt.exists() else ''}"
        except Exception as e:
            logger.error("audio transcription failed: %s", e, exc_info=True)
            await msg.reply_text("Не вдалося обробити аудіо")
            return None
    elif info["type"] == "doc" and info["paths"]:
        media_context = f"Отримано документ: {os.path.basename(info['paths'][0])} (аналіз документів додамо окремо)"
    else:
        media_context = info.get("text") or ""

    if media_context:
        await memory_manager.append_message(chat_id, "tool", f"[MEDIA] {media_context}")
        await memory_manager.ensure_budget(chat_id)

    return user_text or "Проаналізуй наведене медіа і відповідай по суті завдання."

async def handle_telethon_mention(event, bot_username: str) -> Optional[str]:
    txt = (event.raw_text or "") or ""
    user_text = _strip_bot_mention(txt, bot_username)
    target = event.message.reply_to_msg_id
    chat_id = event.chat_id

    if target:
        reply_msg = await event.client.get_messages(entity=event.chat_id, ids=target)
        e2 = event.__class__(event.client, reply_msg, chats=event.chats, users=event.users)
        info = await download_from_telethon_message(e2)
    else:
        info = await download_from_telethon_message(event)

    media_context = ""
    if info["type"] == "photo":
        media_context = describe_images(info["paths"], task_hint=user_text or None)
    elif info["type"] == "video":
        try:
            media_context = analyze_video(info["paths"][0], task_hint=user_text or None)["summary"]
        except Exception as e:
            logger.error("video analysis failed: %s", e, exc_info=True)
            await event.reply(str(e))
            return None
    elif info["type"] in ("voice", "audio"):
        path = info["paths"][0]
        try:
            whisper_transcribe(path)
            from pathlib import Path
            txt = Path(path).with_suffix(".txt")
            media_context = f"Транскрипт аудіо:\n{txt.read_text(encoding='utf-8') if txt.exists() else ''}"
        except Exception as e:
            logger.error("audio transcription failed: %s", e, exc_info=True)
            await event.reply("Не вдалося обробити аудіо")
            return None
    elif info["type"] == "doc" and info["paths"]:
        media_context = f"Отримано документ: {os.path.basename(info['paths'][0])}"
    else:
        media_context = info.get("text") or ""

    if media_context:
        await memory_manager.append_message(chat_id, "tool", f"[MEDIA] {media_context}")
        await memory_manager.ensure_budget(chat_id)

    return user_text or "Проаналізуй наведене медіа і відповідай по суті завдання."
