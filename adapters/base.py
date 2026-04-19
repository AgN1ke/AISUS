from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

MessageHandler = Callable[["UnifiedMessage"], Awaitable[None]]


@dataclass
class MessageParticipant:
    user_id: Optional[int] = None
    username: Optional[str] = None
    display_name: Optional[str] = None


@dataclass
class ReplyTarget:
    message_id: Optional[int] = None
    author: MessageParticipant = field(default_factory=MessageParticipant)
    text: str = ""
    media_kind: Optional[str] = None
    is_bot: bool = False
    sent_at_utc: Optional[str] = None
    sent_at_local: Optional[str] = None


@dataclass
class MessageGeometry:
    chat_type: Optional[str] = None
    current_message_id: Optional[int] = None
    sender: MessageParticipant = field(default_factory=MessageParticipant)
    reply_target: ReplyTarget = field(default_factory=ReplyTarget)
    reply_chain: tuple["ReplyTarget", ...] = field(default_factory=tuple)
    current_media_kind: Optional[str] = None
    target_media_kind: Optional[str] = None
    clean_text: str = ""
    addressed_via_mention: bool = False
    reply_to_bot: bool = False
    addressed: bool = False
    message_sent_at_utc: Optional[str] = None
    message_sent_at_local: Optional[str] = None


@dataclass
class UnifiedMessage:
    # Minimal common slice for Bot API and Telethon.
    platform: str
    chat_id: int
    message_id: int
    text: str
    caption: Optional[str]
    reply_to_message_id: Optional[int]
    has_photo: bool
    has_voice: bool
    has_video: bool
    has_document: bool
    raw_update: Any
    has_video_note: bool = False
    media_group_id: Optional[str] = None

    # Auxiliary routing data.
    bot_username: Optional[str] = None
    geometry: MessageGeometry = field(default_factory=MessageGeometry)


class AbstractAdapter:
    name: str

    async def start(self, handler: MessageHandler) -> None:
        ...

    async def stop(self) -> None:
        ...
