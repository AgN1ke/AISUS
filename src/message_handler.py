from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from adapters.base import UnifiedMessage
from app.message_logic import process_message


class CustomMessageHandler:
    """Legacy-compatible wrapper that delegates PTB updates to the new runtime flow."""

    def __init__(
        self,
        config,
        client,
        voice_processor,
        chat_history_manager,
        openai_wrapper,
    ):
        self.config = config
        self.client = client
        self.voice_processor = voice_processor
        self.chat_history_manager = chat_history_manager
        self.openai_wrapper = openai_wrapper

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        setattr(update, "_bot", context)
        msg = update.effective_message
        if msg is None or update.effective_chat is None:
            return

        unified = UnifiedMessage(
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
            has_video=bool(msg.video),
            has_document=bool(msg.document),
            raw_update=update,
            bot_username=context.bot.username,
        )
        await process_message(unified)


MessageHandler = CustomMessageHandler
