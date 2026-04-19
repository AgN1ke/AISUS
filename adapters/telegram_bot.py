from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telegram.ext import Application, filters
from telegram.ext import CallbackQueryHandler
from telegram.ext import MessageHandler as PTBMessageHandler

from adapters.base import AbstractAdapter, UnifiedMessage
from adapters.base import MessageHandler as UMH
from billing import commands as billing_commands

logger = logging.getLogger(__name__)


def _is_edited_update(update) -> bool:
    return any(
        getattr(update, attr, None) is not None
        for attr in (
            "edited_message",
            "edited_channel_post",
            "edited_business_message",
        )
    )


class TelegramBotAdapter(AbstractAdapter):
    def __init__(self, name: str, token: str):
        self.name = name
        self.token = token
        self.app: Optional[Application] = None
        self._handler: Optional[UMH] = None

    async def start(self, handler: UMH) -> None:
        self._handler = handler
        self.app = Application.builder().token(self.token).build()
        logger.info("telegram_bot.start name=%s", self.name)

        async def _on_message(update, context):
            # attach context for later use
            setattr(update, "_bot", context)
            if _is_edited_update(update):
                logger.info(
                    "telegram_bot.skip_update name=%s reason=edited_message",
                    self.name,
                )
                return
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
                has_voice=bool(msg.voice),
                has_video=bool(msg.video or getattr(msg, "video_note", None)),
                has_document=bool(msg.document),
                raw_update=update,
                has_video_note=bool(getattr(msg, "video_note", None)),
                media_group_id=(
                    str(getattr(msg, "media_group_id", "") or "").strip() or None
                ),
                bot_username=context.bot.username,
            )
            logger.info(
                "telegram_bot.update name=%s chat_id=%s message_id=%s private=%s text_len=%s photo=%s voice=%s video=%s video_note=%s document=%s media_group_id=%s",
                self.name,
                um.chat_id,
                um.message_id,
                getattr(update.effective_chat, "type", None) == "private",
                len((um.text or um.caption or "") or ""),
                um.has_photo,
                um.has_voice,
                um.has_video,
                um.has_video_note,
                um.has_document,
                um.media_group_id or "",
            )
            await handler(um)

        async def _on_callback(update, context):
            setattr(update, "_bot", context)
            callback = getattr(update, "callback_query", None)
            if callback is None:
                return
            handled = await billing_commands.try_handle_callback(
                update,
                getattr(context.bot, "username", None),
            )
            if handled:
                logger.info(
                    "telegram_bot.callback_handled name=%s chat_id=%s message_id=%s data=%s",
                    self.name,
                    getattr(getattr(callback, "message", None), "chat_id", None),
                    getattr(getattr(callback, "message", None), "message_id", None),
                    getattr(callback, "data", None),
                )
                return
            await callback.answer()

        _msg_filters = (
            filters.TEXT
            | filters.PHOTO
            | filters.VIDEO
            | filters.VIDEO_NOTE
            | filters.VOICE
            | filters.AUDIO
            | filters.Document.ALL
            | filters.CAPTION
        )
        self.app.add_handler(PTBMessageHandler(_msg_filters, _on_message))
        self.app.add_handler(CallbackQueryHandler(_on_callback))

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
