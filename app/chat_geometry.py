from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional
from zoneinfo import ZoneInfo

from adapters.base import (
    MessageGeometry,
    MessageParticipant,
    ReplyTarget,
    UnifiedMessage,
)

try:
    _KYIV_TZ = ZoneInfo("Europe/Kiev")
except Exception:
    _KYIV_TZ = timezone.utc


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


def _message_times(message: Any) -> tuple[str | None, str | None]:
    raw = getattr(message, "date", None)
    if raw is None or not isinstance(raw, datetime):
        return None, None
    dt = raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
    utc_dt = dt.astimezone(timezone.utc)
    local_dt = utc_dt.astimezone(_KYIV_TZ)
    return (
        utc_dt.isoformat().replace("+00:00", "Z"),
        local_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
    )


def _participant_label(participant: MessageParticipant) -> str:
    bits = []
    display_name = (participant.display_name or "").strip()
    username = (participant.username or "").strip()
    if display_name:
        bits.append(display_name)
    if username:
        bits.append(f"@{username}")
    if bits:
        return " ".join(bits).strip()
    return str(participant.user_id or "").strip()


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
    if getattr(message, "video", None) or getattr(message, "video_note", None):
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
    if (
        getattr(message, "video", None)
        or getattr(message, "video_note", None)
        or getattr(message, "round", None)
    ):
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


def _is_ptb_message_from_bot(message: Any, bot_username: str, bot_id: int | None) -> bool:
    if message is None:
        return False
    reply_from = getattr(message, "from_user", None)
    if reply_from is None:
        return False
    reply_user_id = getattr(reply_from, "id", None)
    if bot_id is not None and reply_user_id is not None and bot_id == reply_user_id:
        return True
    reply_username = (getattr(reply_from, "username", None) or "").lower()
    return bool(bot_username and reply_username == bot_username.lower())


def _reply_target_from_ptb_message(
    reply: Any,
    bot_username: str,
    bot_id: int | None,
) -> ReplyTarget:
    reply_from = getattr(reply, "from_user", None)
    author = _participant_from_user(reply_from)
    reply_sent_at_utc, reply_sent_at_local = _message_times(reply)
    return ReplyTarget(
        message_id=getattr(reply, "message_id", None),
        author=author,
        text=_message_text(reply),
        media_kind=_ptb_media_kind(reply),
        is_bot=_is_ptb_message_from_bot(reply, bot_username, bot_id),
        sent_at_utc=reply_sent_at_utc,
        sent_at_local=reply_sent_at_local,
    )


def _reply_chain_from_ptb(update: Any, bot_username: str, max_depth: int = 4) -> tuple[ReplyTarget, ...]:
    message = getattr(update, "effective_message", None)
    current = getattr(message, "reply_to_message", None)
    bot = getattr(getattr(update, "_bot", None), "bot", None)
    bot_id = getattr(bot, "id", None)
    chain: list[ReplyTarget] = []
    seen_ids: set[int] = set()
    while current is not None and len(chain) < max_depth:
        current_id = getattr(current, "message_id", None)
        if current_id is not None:
            if current_id in seen_ids:
                break
            seen_ids.add(current_id)
        chain.append(_reply_target_from_ptb_message(current, bot_username, bot_id))
        current = getattr(current, "reply_to_message", None)
    return tuple(chain)


def _reply_target_from_telethon_message(reply: Any, bot_username: str) -> ReplyTarget:
    sender = getattr(reply, "sender", None)
    reply_sent_at_utc, reply_sent_at_local = _message_times(reply)
    reply_username = (getattr(sender, "username", None) or "").lower()
    return ReplyTarget(
        message_id=getattr(reply, "id", None),
        author=_participant_from_user(sender),
        text=str(getattr(reply, "message", None) or "").strip(),
        media_kind=_telethon_media_kind(reply),
        is_bot=bool(getattr(reply, "out", False))
        or bool(bot_username and reply_username == bot_username.lower()),
        sent_at_utc=reply_sent_at_utc,
        sent_at_local=reply_sent_at_local,
    )


async def _reply_chain_from_telethon(
    event: Any,
    bot_username: str,
    max_depth: int = 4,
) -> tuple[ReplyTarget, ...]:
    get_reply_message = getattr(event, "get_reply_message", None)
    if get_reply_message is None:
        return tuple()
    current = await get_reply_message()
    if current is None:
        return tuple()

    client = getattr(event, "client", None)
    chat_id = getattr(event, "chat_id", None)
    chain: list[ReplyTarget] = []
    seen_ids: set[int] = set()
    while current is not None and len(chain) < max_depth:
        current_id = getattr(current, "id", None)
        if current_id is not None:
            if current_id in seen_ids:
                break
            seen_ids.add(current_id)
        chain.append(_reply_target_from_telethon_message(current, bot_username))
        reply_to = getattr(current, "reply_to", None)
        next_id = getattr(reply_to, "reply_to_msg_id", None) if reply_to else None
        if not next_id or client is None or chat_id is None:
            break
        try:
            next_message = await client.get_messages(chat_id, ids=next_id)
        except Exception:
            break
        if isinstance(next_message, list):
            current = next_message[0] if next_message else None
        else:
            current = next_message
    return tuple(chain)


def append_reply_chain_lines(lines: list[str], reply_chain: tuple[ReplyTarget, ...]) -> None:
    if not reply_chain:
        return
    lines.append(f"reply_chain_depth: {len(reply_chain)}")
    for hop, node in enumerate(reply_chain[1:], start=2):
        prefix = f"reply_chain_hop_{hop}"
        if node.message_id is not None:
            lines.append(f"{prefix}_message_id: {node.message_id}")
        if node.sent_at_local:
            lines.append(f"{prefix}_time_local: {node.sent_at_local}")
        if node.sent_at_utc:
            lines.append(f"{prefix}_time_utc: {node.sent_at_utc}")
        author = _participant_label(node.author)
        if author:
            lines.append(f"{prefix}_author: {author}")
        if node.media_kind:
            lines.append(f"{prefix}_media_kind: {node.media_kind}")
        if node.text:
            lines.append(f"{prefix}_text: {node.text[:1200]}")


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
        reply_chain = _reply_chain_from_ptb(update, bot_username)
        reply_target = reply_chain[0] if reply_chain else ReplyTarget()
        current_media_kind = _ptb_media_kind(message)
        message_sent_at_utc, message_sent_at_local = _message_times(message)
        geometry = MessageGeometry(
            chat_type=getattr(getattr(update, "effective_chat", None), "type", None),
            current_message_id=getattr(message, "message_id", None),
            sender=_participant_from_user(getattr(message, "from_user", None)),
            reply_target=reply_target,
            reply_chain=reply_chain,
            current_media_kind=current_media_kind,
            target_media_kind=current_media_kind or reply_target.media_kind,
            clean_text=clean_text,
            addressed_via_mention=mentioned,
            reply_to_bot=reply_to_bot,
            addressed=is_private or mentioned or reply_to_bot,
            message_sent_at_utc=message_sent_at_utc,
            message_sent_at_local=message_sent_at_local,
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
    reply_chain = await _reply_chain_from_telethon(event, bot_username)
    reply_target = reply_chain[0] if reply_chain else ReplyTarget()
    current_media_kind = _telethon_media_kind(message)
    message_sent_at_utc, message_sent_at_local = _message_times(message)
    return MessageGeometry(
        chat_type="private" if is_private else "chat",
        current_message_id=getattr(message, "id", None),
        sender=_participant_from_user(getattr(message, "sender", None)),
        reply_target=reply_target,
        reply_chain=reply_chain,
        current_media_kind=current_media_kind,
        target_media_kind=current_media_kind or reply_target.media_kind,
        clean_text=clean_text,
        addressed_via_mention=mentioned,
        reply_to_bot=reply_to_bot,
        addressed=is_private or mentioned or reply_to_bot,
        message_sent_at_utc=message_sent_at_utc,
        message_sent_at_local=message_sent_at_local,
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
    if geometry.current_message_id is not None:
        lines.append(f"current_message_id: {geometry.current_message_id}")
    if geometry.message_sent_at_local:
        lines.append(f"current_message_time_local: {geometry.message_sent_at_local}")
    if geometry.message_sent_at_utc:
        lines.append(f"current_message_time_utc: {geometry.message_sent_at_utc}")
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
        lines.append(f"reply_target_message_id: {reply.message_id}")
        if reply.sent_at_local:
            lines.append(f"reply_target_time_local: {reply.sent_at_local}")
        if reply.sent_at_utc:
            lines.append(f"reply_target_time_utc: {reply.sent_at_utc}")
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
    append_reply_chain_lines(lines, geometry.reply_chain)
    if geometry.clean_text:
        lines.append(f"current_user_text: {geometry.clean_text[:1200]}")
    return [{"role": "system", "content": "\n".join(lines)}]
