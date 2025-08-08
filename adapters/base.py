from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Any, Awaitable, Callable

MessageHandler = Callable[["UnifiedMessage"], Awaitable[None]]

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

class AbstractAdapter:
    name: str

    async def start(self, handler: MessageHandler) -> None:
        ...

    async def stop(self) -> None:
        ...
