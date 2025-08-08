from __future__ import annotations
import os
from typing import Optional
from telethon import TelegramClient, events

from adapters.base import AbstractAdapter, UnifiedMessage, MessageHandler

class TelethonUserbotAdapter(AbstractAdapter):
    def __init__(self, name: str, api_id: int, api_hash: str, session_path: str):
        self.name = name
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.session_path = session_path
        self.client: Optional[TelegramClient] = None
        self._handler: Optional[MessageHandler] = None

    async def start(self, handler: MessageHandler) -> None:
        self._handler = handler
        os.makedirs(os.path.dirname(self.session_path) or ".", exist_ok=True)
        self.client = TelegramClient(self.session_path, self.api_id, self.api_hash)
        await self.client.start()

        me = await self.client.get_me()
        bot_username = me.username or None

        @self.client.on(events.NewMessage(incoming=True, outgoing=False))
        async def _on_message(event):
            m = event.message
            um = UnifiedMessage(
                platform="telethon",
                chat_id=event.chat_id,
                message_id=m.id,
                text=(m.message or "")[:4096],
                caption=None,
                reply_to_message_id=(m.reply_to.reply_to_msg_id if m.reply_to else None),
                has_photo=bool(m.photo),
                has_voice=bool(getattr(m, "voice", None)) or False,
                has_video=bool(m.video),
                has_document=bool(m.document) and not m.photo and not m.video,
                raw_update=event,
                bot_username=bot_username,
            )
            await handler(um)

        await self.client.run_until_disconnected()

    async def stop(self) -> None:
        if self.client:
            await self.client.disconnect()
