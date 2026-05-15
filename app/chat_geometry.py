from __future__ import annotations

import re
from typing import Any, Optional

from adapters.base import (
    MessageGeometry,
    MessageParticipant,
    ReplyTarget,
    UnifiedMessage,
)


def _display_name(user: Any) -> str:
    if user is None:
        return ""
    full_name = " ".join(
        part
        for part in [
            str(getattr(user, "first_name", "") or "").strip(),
            str(getattr(user, "last_name", "") or "").strip(),
        ]
        if part
    ).strip()
    return full_name or str(getattr(user, "username", "") or "").strip()


def _message_text(message: Any) -> str:
    if message is None:
        return ""
    return str(
        getattr(message, "text", None) or getattr(message, "caption", None) or ""
    ).strip()


def _strip_bot_mention(text: str, bot_username: Optional[str]) -> str:
    cleaned = (text or "").strip()
    if bot_username:
        cleaned = re.sub(
            rf"@{re.escape(bot_username)}\b",
            "",
            cleaned,
            flags=re.I,
        ).strip()
    return cleaned


def _has_mention_ptb(update: Any, bot_username: str) -> bool:
    """Detect @bot mention. Handles three cases:
    1. Literal @username text (most common, especially mobile typing).
    2. 'mention' entity (Telegram-formatted mention with literal text present).
    3. 'text_mention' entity (UI click → entity carries hidden user link, no
       literal text). For text_mention we match by bot.id or entity.user.username.
    """
    msg = getattr(update, "effective_message", None)
    if msg is None:
        return False
    ents = list(getattr(msg, "entities", None) or []) + list(
        getattr(msg, "caption_entities", None) or []
    )
    needle = f"@{bot_username}".lower()
    context = getattr(update, "_bot", None)
    bot = getattr(context, "bot", None)
    bot_id = getattr(bot, "id", None)
    text = _message_text(msg)
    lowered = text.lower()
    for entity in ents:
        entity_type = getattr(entity, "type", None)
        if entity_type == "text_mention":
            user = getattr(entity, "user", None)
            entity_user_id = getattr(user, "id", None)
            entity_username = (getattr(user, "username", None) or "").lower()
            if bot_id is not None and entity_user_id is not None and bot_id == entity_user_id:
                return True
            if bot_username and entity_username == bot_username.lower():
                return True
        if entity_type == "mention" and needle in lowered:
            return True
    return needle in lowered


def _has_mention_text(text: str, bot_username: str) -> bool:
    if not text or not bot_username:
        return False
    return f"@{bot_username}".lower() in text.lower()


def _is_private_ptb(update: Any) -> bool:
    return getattr(getattr(update, "effective_chat", None), "type", None) == "private"


def _is_private_telethon(event: Any) -> bool:
    return bool(getattr(event, "is_private", False))


def _ptb_media_kind(message: Any) -> str | None:
    if message is None:
        return None
    if getattr(message, "photo", None):
        return "image"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "voice", None) or getattr(message, "audio", None):
        return "voice"
    if getattr(message, "document", None):
        return "document"
    return None


def _telethon_media_kind(message: Any) -> str | None:
    if message is None:
        return None
    if getattr(message, "photo", None):
        return "image"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "voice", None) or getattr(message, "audio", None):
        return "voice"
    if getattr(message, "document", None):
        return "document"
    return None


def _is_reply_to_bot_ptb(update: Any, bot_username: str) -> bool:
    msg = getattr(update, "effective_message", None)
    reply = getattr(msg, "reply_to_message", None)
    if reply is None:
        return False

    reply_from = getattr(reply, "from_user", None)
    if reply_from is None:
        return False

    context = getattr(update, "_bot", None)
    bot = getattr(context, "bot", None)
    bot_id = getattr(bot, "id", None)
    reply_user_id = getattr(reply_from, "id", None)
    if bot_id is not None and reply_user_id is not None and bot_id == reply_user_id:
        return True

    reply_username = (getattr(reply_from, "username", None) or "").lower()
    return bool(bot_username and reply_username == bot_username.lower())


async def _is_reply_to_bot_telethon(event: Any, bot_username: str) -> bool:
    get_reply_message = getattr(event, "get_reply_message", None)
    if get_reply_message is None:
        return False

    reply = await get_reply_message()
    if reply is None:
        return False

    if bool(getattr(reply, "out", False)):
        return True

    sender = getattr(reply, "sender", None)
    reply_username = (getattr(sender, "username", None) or "").lower()
    return bool(bot_username and reply_username == bot_username.lower())


def _participant_from_user(user: Any) -> MessageParticipant:
    return MessageParticipant(
        user_id=getattr(user, "id", None),
        username=getattr(user, "username", None),
        display_name=_display_name(user),
    )


def _reply_target_from_ptb(update: Any, bot_username: str) -> ReplyTarget:
    message = getattr(update, "effective_message", None)
    reply = getattr(message, "reply_to_message", None)
    if reply is None:
        return ReplyTarget()
    reply_from = getattr(reply, "from_user", None)
    author = _participant_from_user(reply_from)
    is_bot = _is_reply_to_bot_ptb(update, bot_username)
    return ReplyTarget(
        message_id=getattr(reply, "message_id", None),
        author=author,
        text=_message_text(reply),
        media_kind=_ptb_media_kind(reply),
        is_bot=is_bot,
    )


async def _reply_target_from_telethon(event: Any, bot_username: str) -> ReplyTarget:
    get_reply_message = getattr(event, "get_reply_message", None)
    if get_reply_message is None:
        return ReplyTarget()
    reply = await get_reply_message()
    if reply is None:
        return ReplyTarget()
    sender = getattr(reply, "sender", None)
    return ReplyTarget(
        message_id=getattr(reply, "id", None),
        author=_participant_from_user(sender),
        text=str(getattr(reply, "message", None) or "").strip(),
        media_kind=_telethon_media_kind(reply),
        is_bot=await _is_reply_to_bot_telethon(event, bot_username),
    )


async def resolve_message_geometry(msg: UnifiedMessage) -> MessageGeometry:
    bot_username = msg.bot_username or ""
    if msg.platform == "ptb":
        update = msg.raw_update
        message = getattr(update, "effective_message", None)
        is_private = _is_private_ptb(update)
        clean_text = _strip_bot_mention(_message_text(message), bot_username)
        mentioned = (
            is_private
            or _has_mention_ptb(update, bot_username)
            or _has_mention_text(_message_text(message), bot_username)
        )
        reply_to_bot = (
            False if is_private else _is_reply_to_bot_ptb(update, bot_username)
        )
        reply_target = _reply_target_from_ptb(update, bot_username)
        current_media_kind = _ptb_media_kind(message)
        geometry = MessageGeometry(
            chat_type=getattr(getattr(update, "effective_chat", None), "type", None),
            sender=_participant_from_user(getattr(message, "from_user", None)),
            reply_target=reply_target,
            current_media_kind=current_media_kind,
            target_media_kind=current_media_kind or reply_target.media_kind,
            clean_text=clean_text,
            addressed_via_mention=mentioned,
            reply_to_bot=reply_to_bot,
            addressed=is_private or mentioned or reply_to_bot,
        )
        return geometry

    event = msg.raw_update
    message = getattr(event, "message", None)
    is_private = _is_private_telethon(event)
    clean_text = _strip_bot_mention(
        str(getattr(event, "raw_text", None) or ""), bot_username
    )
    mentioned = is_private or _has_mention_text(
        clean_text or str(getattr(event, "raw_text", None) or ""), bot_username
    )
    reply_to_bot = (
        False if is_private else await _is_reply_to_bot_telethon(event, bot_username)
    )
    reply_target = await _reply_target_from_telethon(event, bot_username)
    current_media_kind = _telethon_media_kind(message)
    return MessageGeometry(
        chat_type="private" if is_private else "chat",
        sender=_participant_from_user(getattr(message, "sender", None)),
        reply_target=reply_target,
        current_media_kind=current_media_kind,
        target_media_kind=current_media_kind or reply_target.media_kind,
        clean_text=clean_text,
        addressed_via_mention=mentioned,
        reply_to_bot=reply_to_bot,
        addressed=is_private or mentioned or reply_to_bot,
    )


def select_ptb_media_target(update: Any) -> Any:
    message = getattr(update, "effective_message", None)
    reply = getattr(message, "reply_to_message", None)
    if _ptb_media_kind(message):
        return message
    if _ptb_media_kind(reply):
        return reply
    return reply or message


async def select_telethon_media_target(event: Any) -> Any:
    message = getattr(event, "message", None)
    if _telethon_media_kind(message):
        return event

    get_reply_message = getattr(event, "get_reply_message", None)
    if get_reply_message is None:
        return event

    reply = await get_reply_message()
    if reply is None:
        return event

    if not _telethon_media_kind(reply):
        return event

    return event.__class__(
        event.client,
        reply,
        chats=event.chats,
        users=event.users,
    )


def render_turn_context_messages(geometry: MessageGeometry) -> list[dict[str, str]]:
    lines = ["[CHAT-GEOMETRY]"]
    if geometry.chat_type:
        lines.append(f"chat_type: {geometry.chat_type}")
    sender = geometry.sender
    if sender.display_name or sender.username:
        sender_bits = [sender.display_name or ""]
        if sender.username:
            sender_bits.append(f"@{sender.username}")
        lines.append(
            f"sender: {' '.join(part for part in sender_bits if part).strip()}"
        )
    lines.append(
        f"addressed_via_mention: {str(bool(geometry.addressed_via_mention)).lower()}"
    )
    lines.append(f"reply_to_bot: {str(bool(geometry.reply_to_bot)).lower()}")
    if geometry.current_media_kind:
        lines.append(f"current_media_kind: {geometry.current_media_kind}")
    if geometry.target_media_kind:
        lines.append(f"target_media_kind: {geometry.target_media_kind}")
    reply = geometry.reply_target
    if reply.message_id is not None:
        lines.append(
            "reply_context_policy: current_user_text is the active request; "
            "reply_target_text is quoted context only. Do not answer "
            "reply_target_text as a second request unless current_user_text asks for it."
        )
        lines.append(f"reply_target_message_id: {reply.message_id}")
        if reply.author.display_name or reply.author.username:
            author_bits = [reply.author.display_name or ""]
            if reply.author.username:
                author_bits.append(f"@{reply.author.username}")
            lines.append(
                f"reply_target_author: {' '.join(part for part in author_bits if part).strip()}"
            )
        lines.append(f"reply_target_is_bot: {str(bool(reply.is_bot)).lower()}")
        if reply.media_kind:
            lines.append(f"reply_target_media_kind: {reply.media_kind}")
        if reply.text:
            lines.append(f"reply_target_text: {reply.text[:1200]}")
    if geometry.clean_text:
        lines.append(f"current_user_text: {geometry.clean_text[:1200]}")
    return [{"role": "system", "content": "\n".join(lines)}]
