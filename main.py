# main.py
from telegram.ext import ApplicationBuilder, MessageHandler, filters
from src.heroku_config_parser import ConfigReader
from src.message_handler import CustomMessageHandler
from src.voice_processor import VoiceProcessor
from src.chat_history_manager import ChatHistoryManager

if __name__ == "__main__":
    config = ConfigReader()

    voice_processor = VoiceProcessor()
    chat_history_manager = ChatHistoryManager()
    message_handler = CustomMessageHandler(config, voice_processor, chat_history_manager)

    app = ApplicationBuilder().token(config.get_api_settings()['bot_token']).build()

    private_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE) & filters.ChatType.PRIVATE,
        message_handler.handle_message
    )

    mentioned_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE) & filters.ChatType.GROUPS & filters.Entity("mention"),
        message_handler.handle_message
    )

    reply_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE) & filters.ChatType.GROUPS & filters.REPLY,
        message_handler.handle_message
    )

    app.add_handler(private_message_handler)
    app.add_handler(mentioned_message_handler)
    app.add_handler(reply_message_handler)

    app.run_polling()
