from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from app.chat_geometry import select_ptb_media_target, select_telethon_media_target
from core.prompts import MEDIA_DEFAULT_TASK_PROMPT
from media.album_registry import get_ptb_album_messages, get_telethon_album_messages
from media.downloader import (
    cleanup_downloaded_media,
    download_from_ptb_album,
    download_from_ptb_message,
    download_from_telethon_album,
    download_from_telethon_message,
)
from media.voice import transcribe_audio
from media.video import analyze_video
from media.vision import describe_images
from memory import memory_manager

logger = logging.getLogger(__name__)


def _planner_media_kind(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    mapping = {
        "photo": "image",
        "image": "image",
        "video": "video",
        "voice": "voice",
        "audio": "voice",
        "doc": "document",
        "document": "document",
        "album": "album",
    }
    return mapping.get(normalized)


def _strip_bot_mention(text: str, bot_username: Optional[str]) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    if bot_username:
        cleaned = re.sub(
            rf"@{re.escape(bot_username)}\b", "", cleaned, flags=re.I
        ).strip()
    return cleaned


def _compose_media_bundle(
    *,
    media_type: str,
    post_text: str | None = None,
    media_analysis: str | None = None,
    transcript: str | None = None,
) -> str:
    lines = [f"target_media_type: {media_type}"]
    cleaned_post_text = (post_text or "").strip()
    cleaned_analysis = (media_analysis or "").strip()
    cleaned_transcript = (transcript or "").strip()
    if cleaned_post_text:
        lines.append(f"target_post_text: {cleaned_post_text[:4000]}")
    if cleaned_transcript:
        lines.append(f"audio_transcript: {cleaned_transcript[:6000]}")
    if cleaned_analysis:
        lines.append(f"media_analysis: {cleaned_analysis[:8000]}")
    return "\n".join(lines).strip()


def _compose_album_bundle(
    *,
    post_text: str | None = None,
    route_kind: str | None = None,
    group_id: str | None = None,
    items: list[dict] | None = None,
) -> str:
    album_items = items or []
    contains_types = []
    lines = ["target_media_type: album"]
    if group_id:
        lines.append(f"album_group_id: {group_id}")
    lines.append(f"album_item_count: {len(album_items)}")
    if route_kind:
        lines.append(f"album_route_media_kind: {route_kind}")
    if post_text:
        lines.append(f"target_post_text: {post_text[:4000]}")
    lines.append(
        "album_semantics: Сприймай це як один Telegram-пост із кількома медіаелементами. Підпис і запит користувача відносяться до всього альбому, якщо явно не сказано інакше."
    )
    for index, item in enumerate(album_items, start=1):
        item_type = (item.get("type") or "").strip()
        if item_type and item_type not in contains_types:
            contains_types.append(item_type)
        lines.append(f"album_item_{index}_type: {item_type}")
        if item.get("message_id") is not None:
            lines.append(f"album_item_{index}_message_id: {item.get('message_id')}")
        item_text = (item.get("text") or "").strip()
        if item_text:
            lines.append(f"album_item_{index}_post_text: {item_text[:2000]}")
        item_transcript = (item.get("transcript") or "").strip()
        if item_transcript:
            lines.append(
                f"album_item_{index}_audio_transcript: {item_transcript[:4000]}"
            )
        item_analysis = (item.get("analysis") or "").strip()
        if item_analysis:
            lines.append(f"album_item_{index}_media_analysis: {item_analysis[:4000]}")
    if contains_types:
        lines.append(f"album_contains_types: {', '.join(contains_types)}")
    return "\n".join(lines).strip()


def _build_task_aware_media_hint(
    task_hint: str | None,
    post_text: str | None = None,
) -> str | None:
    user_request = (task_hint or "").strip()
    target_caption = (post_text or "").strip()
    lines: list[str] = []
    if user_request:
        lines.append(f"Запит користувача до цього медіа: {user_request[:1000]}")
    if target_caption and target_caption != user_request:
        lines.append(f"Підпис або текст медіа: {target_caption[:1000]}")
    if not lines:
        return None
    lines.append(
        "Сфокусуй аналіз на деталях, потрібних для відповіді на цей запит. "
        "Якщо питають 'хто це' або 'що це', дай максимально конкретну "
        "ідентифікацію; якщо точність невисока, назви найімовірніші варіанти "
        "і видимі ознаки. Якщо питають 'що робить', опиши дію. "
        "Не відповідай користувачу напряму: дай факти для фінального агента."
    )
    return "\n".join(lines)


async def _build_media_context(
    info: dict, task_hint: str | None, on_error
) -> tuple[str, str | None]:
    media_type = info.get("type")
    paths = info.get("paths") or []
    post_text = (info.get("text") or "").strip()
    media_task_hint = _build_task_aware_media_hint(task_hint, post_text)

    if media_type == "album":
        items = []
        route_kind = (info.get("route_kind") or "").strip() or None
        for raw_item in info.get("items") or []:
            item_type = (raw_item.get("type") or "").strip().lower()
            item_paths = raw_item.get("paths") or []
            item_error = raw_item.get("error_reason")
            item_payload = {
                "type": item_type,
                "message_id": raw_item.get("message_id"),
                "text": (raw_item.get("text") or "").strip(),
                "analysis": "",
                "transcript": "",
            }
            if item_error:
                # Download failed (e.g. file too big) — inject error as analysis
                item_payload["analysis"] = item_error
            elif item_type == "photo" and item_paths:
                try:
                    item_task_hint = _build_task_aware_media_hint(
                        task_hint, item_payload["text"] or post_text
                    )
                    item_payload["analysis"] = await asyncio.to_thread(
                        describe_images, item_paths, item_task_hint,
                    )
                except Exception as exc:
                    logger.error("album photo analysis failed: %s", exc, exc_info=True)
                    item_payload["analysis"] = f"Не вдалося проаналізувати фото: {exc}"
            elif item_type == "video" and item_paths:
                try:
                    item_task_hint = _build_task_aware_media_hint(
                        task_hint, item_payload["text"] or post_text
                    )
                    video_payload = await asyncio.to_thread(
                        analyze_video, item_paths[0], item_task_hint,
                    )
                    item_payload["analysis"] = video_payload.get("summary") or ""
                    item_payload["transcript"] = (
                        video_payload.get("transcript") or ""
                    ).strip()
                except Exception as exc:
                    logger.error("album video analysis failed: %s", exc, exc_info=True)
                    item_payload["analysis"] = f"Не вдалося проаналізувати відео: {exc}"
            elif item_type in {"voice", "audio"} and item_paths:
                try:
                    transcript = await transcribe_audio(item_paths[0])
                    item_payload["transcript"] = (transcript or "").strip()
                except Exception as exc:
                    logger.error("album audio transcription failed: %s", exc, exc_info=True)
                    item_payload["analysis"] = f"Не вдалося обробити аудіо: {exc}"
            elif item_type == "doc" and item_paths:
                item_payload["analysis"] = (
                    "Отримано документ: "
                    f"{os.path.basename(item_paths[0])} "
                    "(аналіз документів додамо окремо)"
                )
            items.append(item_payload)

        return (
            _compose_album_bundle(
                post_text=post_text,
                route_kind=route_kind,
                group_id=info.get("group_id"),
                items=items,
            ),
            None,
        )

    # If download failed, inject error into context so bot knows what happened
    download_error = info.get("error_reason")
    if download_error:
        return (
            _compose_media_bundle(
                media_type=media_type or "media",
                post_text=post_text,
                media_analysis=download_error,
            ),
            None,
        )

    if media_type == "photo" and paths:
        try:
            analysis = await asyncio.to_thread(describe_images, paths, media_task_hint)
        except Exception as exc:
            logger.error("photo analysis failed: %s", exc, exc_info=True)
            analysis = f"Не вдалося проаналізувати фото: {exc}"
        if not (analysis or "").strip():
            logger.warning("photo analysis returned empty result paths=%s", len(paths))
            analysis = "Не вдалося проаналізувати фото: vision-модель повернула порожній опис."
        return (
            _compose_media_bundle(
                media_type="photo",
                post_text=post_text,
                media_analysis=analysis,
            ),
            None,
        )

    if media_type == "video" and paths:
        try:
            payload = await asyncio.to_thread(analyze_video, paths[0], media_task_hint)
        except Exception as exc:
            logger.error("video analysis failed: %s", exc, exc_info=True)
            return (
                _compose_media_bundle(
                    media_type="video",
                    post_text=post_text,
                    media_analysis=f"Не вдалося проаналізувати відео: {exc}",
                ),
                None,
            )
        return (
            _compose_media_bundle(
                media_type="video",
                post_text=post_text,
                transcript=(payload.get("transcript") or "").strip(),
                media_analysis=payload.get("summary") or "",
            ),
            None,
        )

    if media_type in ("voice", "audio") and paths:
        try:
            transcript = await transcribe_audio(paths[0])
        except Exception as exc:
            logger.error("audio transcription failed: %s", exc, exc_info=True)
            return (
                _compose_media_bundle(
                    media_type=media_type,
                    post_text=post_text,
                    media_analysis=f"Не вдалося обробити аудіо: {exc}",
                ),
                None,
            )
        return (
            _compose_media_bundle(
                media_type=media_type,
                post_text=post_text,
                transcript=transcript,
            ),
            (transcript or "").strip() or None,
        )

    if media_type == "doc" and paths:
        return (
            _compose_media_bundle(
                media_type="document",
                post_text=post_text,
                media_analysis=(
                    "Отримано документ: "
                    f"{os.path.basename(paths[0])} "
                    "(аналіз документів додамо окремо)"
                ),
            ),
            None,
        )

    return post_text, None


async def _append_media_context(chat_id: int, media_context: str) -> None:
    if not media_context:
        return
    await memory_manager.append_message(chat_id, "system", f"[MEDIA] {media_context}")
    await memory_manager.ensure_budget(chat_id)


async def handle_ptb_mention(
    update, context, bot_username: str
) -> tuple[Optional[str], str | None]:
    msg = update.effective_message
    chat_id = update.effective_chat.id
    logger.info("media.ptb.start chat_id=%s message_id=%s", chat_id, msg.message_id)
    on_error = getattr(msg, "reply_text", None)
    if on_error is None:

        async def on_error(_text: str) -> None:
            return None

    user_text = _strip_bot_mention((msg.text or msg.caption or "") or "", bot_username)
    target = select_ptb_media_target(update)
    album_messages = get_ptb_album_messages(target)
    if len(album_messages) > 1:
        info = await download_from_ptb_album(album_messages, context)
    else:
        info = await download_from_ptb_message(target, context)
    try:
        logger.info(
            "media.ptb.downloaded chat_id=%s media_type=%s paths=%s",
            chat_id,
            info.get("type"),
            len(info.get("paths") or []),
        )
        logger.info(
            "media.ptb.target chat_id=%s target_message_id=%s target_text_len=%s user_text_len=%s album_items=%s route_kind=%s",
            chat_id,
            getattr(target, "message_id", None),
            len((info.get("text") or "").strip()),
            len(user_text or ""),
            len(info.get("items") or []),
            info.get("route_kind") or "",
        )
        media_context, semantic_text = await _build_media_context(info, user_text, on_error)
        await _append_media_context(chat_id, media_context)
        logger.info(
            "media.ptb.done chat_id=%s context_len=%s user_text_len=%s semantic_text_len=%s",
            chat_id,
            len(media_context or ""),
            len(user_text or ""),
            len(semantic_text or ""),
        )
        return (
            user_text or semantic_text or MEDIA_DEFAULT_TASK_PROMPT,
            _planner_media_kind(info.get("route_kind") or info.get("type")),
            media_context,
        )
    finally:
        await cleanup_downloaded_media(info.get("paths") or [])


async def handle_telethon_mention(
    event, bot_username: str
) -> tuple[Optional[str], str | None]:
    chat_id = event.chat_id
    logger.info("media.telethon.start chat_id=%s message_id=%s", chat_id, event.id)
    user_text = _strip_bot_mention((event.raw_text or "") or "", bot_username)
    target_event = await select_telethon_media_target(event)
    album_messages = get_telethon_album_messages(target_event)
    if len(album_messages) > 1:
        album_events = [
            target_event.__class__(
                target_event.client,
                raw_message,
                chats=target_event.chats,
                users=target_event.users,
            )
            for raw_message in album_messages
        ]
        info = await download_from_telethon_album(album_events)
    else:
        info = await download_from_telethon_message(target_event)
    try:
        logger.info(
            "media.telethon.downloaded chat_id=%s media_type=%s paths=%s",
            chat_id,
            info.get("type"),
            len(info.get("paths") or []),
        )
        logger.info(
            "media.telethon.target chat_id=%s target_message_id=%s target_text_len=%s user_text_len=%s album_items=%s route_kind=%s",
            chat_id,
            getattr(target_event, "id", None),
            len((info.get("text") or "").strip()),
            len(user_text or ""),
            len(info.get("items") or []),
            info.get("route_kind") or "",
        )
        media_context, semantic_text = await _build_media_context(
            info, user_text, event.reply
        )
        await _append_media_context(chat_id, media_context)
        logger.info(
            "media.telethon.done chat_id=%s context_len=%s user_text_len=%s semantic_text_len=%s",
            chat_id,
            len(media_context or ""),
            len(user_text or ""),
            len(semantic_text or ""),
        )
        return (
            user_text or semantic_text or MEDIA_DEFAULT_TASK_PROMPT,
            _planner_media_kind(info.get("route_kind") or info.get("type")),
            media_context,
        )
    finally:
        await cleanup_downloaded_media(info.get("paths") or [])
