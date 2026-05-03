from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any, Awaitable, Callable

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


@dataclass
class MessageGeometry:
    chat_type: Optional[str] = None
    sender: MessageParticipant = field(default_factory=MessageParticipant)
    reply_target: ReplyTarget = field(default_factory=ReplyTarget)
    current_media_kind: Optional[str] = None
    target_media_kind: Optional[str] = None
    clean_text: str = ""
    addressed_via_mention: bool = False
    reply_to_bot: bool = False
    addressed: bool = False


@dataclass
class UnifiedMessage:
    # Мінімальний зріз даних, спільний для Bot API та Telethon
    platform: str              # "ptb" або "telethon"
    chat_id: int
    message_id: int
    text: str
    caption: Optional[str]
    reply_to_message_id: Optional[int]
    has_photo: bool
    has_voice: bool
    has_video: bool
    has_document: bool
    raw_update: Any            # сирий Update (PTB) або Event (Telethon)

    # Допоміжне
    bot_username: Optional[str] = None
    geometry: MessageGeometry = field(default_factory=MessageGeometry)
    has_video_note: bool = False
    media_group_id: Optional[str] = None

class AbstractAdapter:
    name: str

    async def start(self, handler: MessageHandler) -> None:
        ...

    async def stop(self) -> None:
        ...
