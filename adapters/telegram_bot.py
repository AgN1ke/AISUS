from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telegram.ext import Application, filters
from telegram.ext import MessageHandler as PTBMessageHandler

from adapters.base import AbstractAdapter, UnifiedMessage
from adapters.base import MessageHandler as UMH
from media.album_registry import observe_album_message

logger = logging.getLogger(__name__)


class TelegramBotAdapter(AbstractAdapter):
    def __init__(self, name: str, token: str):
        self.name = name
        self.token = token
        self.app: Optional[Application] = None
        self._handler: Optional[UMH] = None

    async def start(self, handler: UMH) -> None:
        self._handler = handler
        # concurrent_updates=True is essential for albums: while item-1's handler
        # is in settle/download, items 2..N must arrive in parallel so they can
        # be observed in the registry before settle ends. Without this, PTB
        # serializes handlers and album collection always sees only 1 item.
        self.app = (
            Application.builder().token(self.token).concurrent_updates(True).build()
        )
        logger.info("telegram_bot.start name=%s", self.name)

        async def _on_message(update, context):
            # attach context for later use
            setattr(update, "_bot", context)
            msg = update.effective_message
            if msg is None or update.effective_chat is None:
                logger.warning(
                    "telegram_bot.skip_update name=%s reason=no_effective_message",
                    self.name,
                )
                return
            um = UnifiedMessage(
                platform="ptb",
                chat_id=update.effective_chat.id,
                message_id=msg.message_id,
                text=(msg.text or "")[:4096],
                caption=(msg.caption or None),
                reply_to_message_id=(
                    msg.reply_to_message.message_id if msg.reply_to_message else None
                ),
                has_photo=bool(msg.photo),
                has_voice=bool(msg.voice or msg.audio),
                has_video=bool(msg.video),
                has_document=bool(msg.document),
                raw_update=update,
                bot_username=context.bot.username,
                has_video_note=bool(getattr(msg, "video_note", None)),
                media_group_id=(str(msg.media_group_id) if msg.media_group_id else None),
            )
            # Register album items as early as possible — before any heavy
            # handler work — so siblings always end up in the registry
            # regardless of processing order.
            if um.media_group_id:
                observe_album_message(um)
            logger.info(
                "telegram_bot.update name=%s chat_id=%s message_id=%s private=%s text_len=%s photo=%s voice=%s video=%s document=%s media_group_id=%s",
                self.name,
                um.chat_id,
                um.message_id,
                getattr(update.effective_chat, "type", None) == "private",
                len((um.text or um.caption or "") or ""),
                um.has_photo,
                um.has_voice,
                um.has_video,
                um.has_document,
                um.media_group_id or "",
            )
            await handler(um)

        self.app.add_handler(PTBMessageHandler(filters.ALL, _on_message))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        logger.info("telegram_bot.polling_started name=%s", self.name)

    async def stop(self) -> None:
        if not self.app:
            return
        logger.info("telegram_bot.stop name=%s", self.name)
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()
