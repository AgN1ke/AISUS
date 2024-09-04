# main.py
import os
import base64
from configparser import ConfigParser
from telegram.ext import ApplicationBuilder, MessageHandler, filters
from src.message_handler import CustomMessageHandler
from src.voice_processor import VoiceProcessor
from src.openai_wrapper import OpenAIWrapper
from src.chat_history_manager import ChatHistoryManager


def get_config():
    # Декодування конфігураційної строки з Base64
    config_base64 = os.getenv('CONFIG_BASE64')
    config_decoded = base64.b64decode(config_base64).decode('utf-8')

    # Читання конфігурації з декодованої строки
    config = ConfigParser()
    config.read_string(config_decoded)
    return config


if __name__ == "__main__":
    config = get_config()

    voice_processor = VoiceProcessor(api_key=config.get('openai_settings', 'api_key'),
                                     whisper_model=config.get('openai_settings', 'whisper_model'),
                                     tts_model=config.get('openai_settings', 'tts_model'))
    chat_history_manager = ChatHistoryManager()
    openai_wrapper = OpenAIWrapper(config.get('openai_settings', 'api_key'))
    message_handler = CustomMessageHandler(config, voice_processor, chat_history_manager, openai_wrapper)

    app = ApplicationBuilder().token(config.get('api_settings', 'bot_token')).build()

    # Создание обработчиков сообщений для разных случаев
    private_message_handler = MessageHandler((filters.TEXT | filters.VOICE) & filters.ChatType.PRIVATE,
                                             message_handler.handle_message)
    mentioned_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE) & filters.ChatType.GROUPS & filters.Entity("mention"),
        message_handler.handle_message)
    reply_message_handler = MessageHandler((filters.TEXT | filters.VOICE) & filters.ChatType.GROUPS & filters.REPLY,
                                           message_handler.handle_message)

    # Добавление обработчиков в приложение
    app.add_handler(private_message_handler)
    app.add_handler(mentioned_message_handler)
    app.add_handler(reply_message_handler)

    app.run_polling()
