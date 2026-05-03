"""Voice synthesis (TTS) and transcription (STT) for @saintaibot.

Master-branch version — no per-user voice settings, just env-configured voice.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import uuid
from pathlib import Path

from adapters.base import UnifiedMessage
from agent.llm import get_llm_client
from core.env import (
    openai_stt_api_key,
    openai_tts_api_key,
    stt_base_url,
    tts_base_url,
    tts_model,
    vocalizer_voice,
    whisper_model,
)
from media.downloader import MEDIA_TMP

logger = logging.getLogger(__name__)

_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_LINKED_CITATION_RE = re.compile(r"\[\[(\d{1,2})\]\]\((https?://[^\s)]+)\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_RAW_URL_RE = re.compile(r"https?://\S+")
_FOOTNOTE_CITATION_RE = re.compile(r"\[(\d{1,2})\]")
_WHITESPACE_RE = re.compile(r"[ \t]+")


def _stt_client():
    api_key = openai_stt_api_key()
    if not api_key:
        raise RuntimeError("STT API key is not configured")
    return get_llm_client("openai_stt", api_key, stt_base_url())


def _tts_client():
    api_key = openai_tts_api_key()
    if not api_key:
        raise RuntimeError("TTS API key is not configured")
    return get_llm_client("openai_tts", api_key, tts_base_url())


def normalize_tts_text(text: str) -> str:
    value = html.unescape(str(text or "")).replace("\r\n", "\n").strip()
    if not value:
        return ""
    value = _LINKED_CITATION_RE.sub("", value)
    value = _MARKDOWN_LINK_RE.sub(lambda m: m.group(1).strip(), value)
    value = _RAW_URL_RE.sub("", value)
    value = _HTML_TAG_RE.sub("", value)
    value = value.replace("```", "\n").replace("`", "")
    value = value.replace("**", "").replace("*", "").replace("_", "")
    value = _FOOTNOTE_CITATION_RE.sub("", value)
    value = _WHITESPACE_RE.sub(" ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r" ?\n ?", "\n", value)
    return value.strip()


def split_tts_text(text: str, max_chars: int = 3500) -> list[str]:
    cleaned = normalize_tts_text(text)
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]
    parts = re.split(r"(?<=[.!?…])\s+|\n+", cleaned)
    chunks: list[str] = []
    current = ""
    for part in [item.strip() for item in parts if item.strip()]:
        candidate = part if not current else f"{current} {part}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = part
        while len(current) > max_chars:
            split_at = current.rfind(" ", 0, max_chars)
            if split_at < max_chars // 2:
                split_at = max_chars
            chunks.append(current[:split_at].strip())
            current = current[split_at:].strip()
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _transcribe_sync(path: str) -> str:
    model = whisper_model()
    with open(path, "rb") as audio_file:
        response = _stt_client().audio.transcriptions.create(
            file=audio_file,
            model=model,
            language="uk",
            response_format="text",
        )
    if isinstance(response, str):
        return response.strip()
    return str(getattr(response, "text", "") or "").strip()


def transcribe_audio_sync(path: str) -> str:
    return _transcribe_sync(path)


async def transcribe_audio(path: str) -> str:
    return await asyncio.to_thread(_transcribe_sync, path)


def _synthesize_chunk_sync(text: str, index: int) -> str:
    response = _tts_client().audio.speech.create(
        model=tts_model(),
        voice=vocalizer_voice(),
        input=text,
        response_format="opus",
    )
    file_name = MEDIA_TMP / f"tts_{uuid.uuid4().hex}_{index:02d}.ogg"
    with open(file_name, "wb") as audio_file:
        audio_file.write(response.read())
    return str(file_name)


async def synthesize_voice_chunks(text: str) -> list[str]:
    chunks = split_tts_text(text)
    if not chunks:
        raise RuntimeError("No text to speak")
    paths: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        path = await asyncio.to_thread(_synthesize_chunk_sync, chunk, index)
        paths.append(path)
    return paths


async def cleanup_voice_files(paths: list[str]) -> None:
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            logger.warning("voice.cleanup_failed path=%s", path, exc_info=True)


async def _send_ptb_voice(msg: UnifiedMessage, path: str, reply_to: int | None) -> None:
    message = msg.raw_update.effective_message
    kwargs = {
        "read_timeout": 180,
        "write_timeout": 180,
        "connect_timeout": 30,
        "pool_timeout": 30,
    }
    if reply_to is not None:
        kwargs["reply_to_message_id"] = reply_to
    with open(path, "rb") as audio_file:
        if hasattr(message, "reply_voice"):
            await message.reply_voice(voice=audio_file, **kwargs)
            return
        bot = getattr(getattr(msg.raw_update, "_bot", None), "bot", None)
        if bot is None:
            raise RuntimeError("PTB bot context is missing for voice reply")
        await bot.send_voice(chat_id=msg.chat_id, voice=audio_file, **kwargs)


async def send_voice_response(
    msg: UnifiedMessage,
    text: str,
    *,
    reply_to: int | None = None,
) -> None:
    paths = await synthesize_voice_chunks(text)
    try:
        for index, path in enumerate(paths):
            chunk_reply_to = reply_to if index == 0 else None
            await _send_ptb_voice(msg, path, chunk_reply_to)
    finally:
        await cleanup_voice_files(paths)
