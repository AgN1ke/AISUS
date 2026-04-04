from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

from app.chat_geometry import select_ptb_media_target, select_telethon_media_target
from core.prompts import MEDIA_DEFAULT_TASK_PROMPT
from media.downloader import download_from_ptb_message, download_from_telethon_message
from media.video import analyze_video
from media.vision import describe_images
from memory import memory_manager
from whisper_tool import transcribe as whisper_transcribe

logger = logging.getLogger(__name__)


def _strip_bot_mention(text: str, bot_username: Optional[str]) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    if bot_username:
        cleaned = re.sub(
            rf"@{re.escape(bot_username)}\b", "", cleaned, flags=re.I
        ).strip()
    return cleaned


def _transcribe_media(path: str) -> str:
    whisper_transcribe(path)
    transcript_path = Path(path).with_suffix(".txt")
    return (
        transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
    )


async def _build_media_context(info: dict, task_hint: str | None, on_error) -> str:
    media_type = info.get("type")
    paths = info.get("paths") or []

    if media_type == "photo" and paths:
        return describe_images(paths, task_hint=task_hint or None)

    if media_type == "video" and paths:
        try:
            return analyze_video(paths[0], task_hint=task_hint or None)["summary"]
        except Exception as exc:
            logger.error("video analysis failed: %s", exc, exc_info=True)
            await on_error(str(exc))
            return ""

    if media_type in ("voice", "audio") and paths:
        try:
            transcript = _transcribe_media(paths[0])
        except Exception as exc:
            logger.error("audio transcription failed: %s", exc, exc_info=True)
            await on_error("Не вдалося обробити аудіо")
            return ""
        return f"Транскрипт аудіо:\n{transcript}"

    if media_type == "doc" and paths:
        return f"Отримано документ: {os.path.basename(paths[0])} (аналіз документів додамо окремо)"

    return info.get("text") or ""


async def _append_media_context(chat_id: int, media_context: str) -> None:
    if not media_context:
        return
    await memory_manager.append_message(chat_id, "system", f"[MEDIA] {media_context}")
    await memory_manager.ensure_budget(chat_id)


async def handle_ptb_mention(update, context, bot_username: str) -> Optional[str]:
    msg = update.effective_message
    chat_id = update.effective_chat.id
    logger.info("media.ptb.start chat_id=%s message_id=%s", chat_id, msg.message_id)
    on_error = getattr(msg, "reply_text", None)
    if on_error is None:

        async def on_error(_text: str) -> None:
            return None

    user_text = _strip_bot_mention((msg.text or msg.caption or "") or "", bot_username)
    target = select_ptb_media_target(update)

    info = await download_from_ptb_message(target, context)
    logger.info(
        "media.ptb.downloaded chat_id=%s media_type=%s paths=%s",
        chat_id,
        info.get("type"),
        len(info.get("paths") or []),
    )
    media_context = await _build_media_context(info, user_text, on_error)
    await _append_media_context(chat_id, media_context)
    logger.info(
        "media.ptb.done chat_id=%s context_len=%s user_text_len=%s",
        chat_id,
        len(media_context or ""),
        len(user_text or ""),
    )

    return user_text or MEDIA_DEFAULT_TASK_PROMPT


async def handle_telethon_mention(event, bot_username: str) -> Optional[str]:
    chat_id = event.chat_id
    logger.info("media.telethon.start chat_id=%s message_id=%s", chat_id, event.id)
    user_text = _strip_bot_mention((event.raw_text or "") or "", bot_username)
    target_event = await select_telethon_media_target(event)
    info = await download_from_telethon_message(target_event)

    logger.info(
        "media.telethon.downloaded chat_id=%s media_type=%s paths=%s",
        chat_id,
        info.get("type"),
        len(info.get("paths") or []),
    )
    media_context = await _build_media_context(info, user_text, event.reply)
    await _append_media_context(chat_id, media_context)
    logger.info(
        "media.telethon.done chat_id=%s context_len=%s user_text_len=%s",
        chat_id,
        len(media_context or ""),
        len(user_text or ""),
    )

    return user_text or MEDIA_DEFAULT_TASK_PROMPT
