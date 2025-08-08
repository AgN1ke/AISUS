from __future__ import annotations
import asyncio
from typing import Optional
from telegram.ext import Application, MessageHandler as PTBMessageHandler, filters

from adapters.base import AbstractAdapter, UnifiedMessage, MessageHandler as UMH

class TelegramBotAdapter(AbstractAdapter):
    def __init__(self, name: str, token: str):
        self.name = name
        self.token = token
        self.app: Optional[Application] = None
        self._handler: Optional[UMH] = None

    async def start(self, handler: UMH) -> None:
        self._handler = handler
        self.app = Application.builder().token(self.token).build()

        async def _on_message(update, context):
            # attach context for later use
            setattr(update, "_bot", context)
            msg = update.effective_message
            um = UnifiedMessage(
                platform="ptb",
                chat_id=update.effective_chat.id,
                message_id=msg.message_id,
                text=(msg.text or "")[:4096],
                caption=(msg.caption or None),
                reply_to_message_id=(msg.reply_to_message.message_id if msg.reply_to_message else None),
                has_photo=bool(msg.photo),
                has_voice=bool(msg.voice),
                has_video=bool(msg.video),
                has_document=bool(msg.document),
                raw_update=update,
                bot_username=context.bot.username,
            )
            await handler(um)

        self.app.add_handler(PTBMessageHandler(filters.ALL, _on_message))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        if not self.app:
            return
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
