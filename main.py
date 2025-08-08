#main.py

from telegram.ext import ApplicationBuilder, MessageHandler, filters
from db.bootstrap import bootstrap_db, bootstrap_db_sync
from src.heroku_config_parser import ConfigReader
from src.message_handler import CustomMessageHandler
from src.voice_processor import VoiceProcessor
from src.openai_wrapper import OpenAIWrapper
from src.chat_history_manager import ChatHistoryManager

if __name__ == "__main__":
    config = ConfigReader()

    voice_processor = VoiceProcessor(api_key=config.get_openai_settings()['api_key'],
                                     whisper_model=config.get_openai_settings()['whisper_model'],
                                     tts_model=config.get_openai_settings()['tts_model'])
    chat_history_manager = ChatHistoryManager()
    openai_wrapper = OpenAIWrapper(config.get_openai_settings()['api_key'])
    message_handler = CustomMessageHandler(config, voice_processor, chat_history_manager, openai_wrapper)

    app = ApplicationBuilder().token(config.get_api_settings()['bot_token']).build()

    # Создание обработчиков сообщений для разных случаев
    private_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO) & filters.ChatType.PRIVATE,
        message_handler.handle_message
    )

    mentioned_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO) & filters.ChatType.GROUPS & filters.Entity("mention"),
        message_handler.handle_message
    )

    reply_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO) & filters.ChatType.GROUPS & filters.REPLY,
        message_handler.handle_message
    )

    # Добавление обработчиков в приложение
    app.add_handler(private_message_handler)
    app.add_handler(mentioned_message_handler)
    app.add_handler(reply_message_handler)

    bootstrap_db_sync()
    app.run_polling()
