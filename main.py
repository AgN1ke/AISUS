# main.py
from pyrogram import Client
from src.config_reader import ConfigReader
from src.message_handler import MessageHandler
from src.voice_processor import VoiceProcessor
from src.openai_wrapper import OpenAIWrapper
from src.chat_history_manager import ChatHistoryManager


if __name__ == "__main__":
    config = ConfigReader('configs/config.ini')

    app = Client(name=config.get_api_settings()['session_name'],
                 api_id=config.get_api_settings()['api_id'],
                 api_hash=config.get_api_settings()['api_hash'])
    voice_processor = VoiceProcessor(api_key=config.get_openai_settings()['api_key'],
                                     whisper_model=config.get_openai_settings()['whisper_model'],
                                     tts_model=config.get_openai_settings()['tts_model'])
    chat_history_manager = ChatHistoryManager()
    openai_wrapper = OpenAIWrapper(config.get_openai_settings()['api_key'])
    message_handler = MessageHandler(config, app, voice_processor, chat_history_manager, openai_wrapper)

    app.run()
