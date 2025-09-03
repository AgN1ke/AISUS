import logging
from telegram import Bot
from src.aisus.message_wrapper import MessageWrapper

logger = logging.getLogger(__name__)


class MessageRouter:
    """Decides whether an incoming message should be processed."""

    @staticmethod
    async def should_process(bot: Bot, message: MessageWrapper) -> bool:
        is_private = getattr(message, "chat_type", None) == "private"
        text = getattr(message, "text", "") or ""
        caption = getattr(message, "caption", "") or ""
        bot_username = (await bot.get_me()).username
        has_mention = (f"@{bot_username}" in text) or (f"@{bot_username}" in caption)
        is_reply_to_bot = bool(
            getattr(message, "reply_to_message", None)
            and getattr(message, "reply_to_message_from_user_username", None) == bot_username
        )
        return is_private or has_mention or is_reply_to_bot
