# main.py
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler as TgCommandHandler

from src.aisus.chat_history_manager import ChatHistoryManager
from src.aisus.config_parser import ConfigReader
from src.aisus.message_handler import CustomMessageHandler
from src.aisus.openai_wrapper import OpenAIWrapper
from src.aisus.voice_processor import VoiceProcessor
from src.aisus.handlers.message_router import MessageRouter
from src.aisus.handlers.command_handler import CommandHandler
from src.aisus.services.auth import AuthService
from src.aisus.services.stats import StatsService

if __name__ == "__main__":
    config = ConfigReader()

    voice_processor = VoiceProcessor(
        api_key=config.get_openai_settings()['api_key'],
        whisper_model=config.get_openai_settings()['whisper_model'],
        tts_model=config.get_openai_settings()['tts_model']
    )
    chat_history_manager = ChatHistoryManager()
    openai_wrapper = OpenAIWrapper(
        api_key=config.get_openai_settings()['api_key'],
        api_mode=config.get_openai_settings()['api_mode'],
        reasoning_effort=config.get_openai_settings()['reasoning_effort'],
        search_enabled=config.get_openai_settings()["search_enabled"]
    )

    openai_wrapper.restore_vector_stores()

    auth_service = AuthService(config)
    stats_service = StatsService()
    message_router = MessageRouter()
    command_handler = CommandHandler(
        config,
        voice_processor,
        chat_history_manager,
        openai_wrapper,
        auth_service,
        stats_service,
    )
    message_handler = CustomMessageHandler(
        config,
        voice_processor,
        chat_history_manager,
        openai_wrapper,
        message_router,
        auth_service,
        stats_service,
    )

    app = ApplicationBuilder().token(config.get_api_settings()['bot_token']).build()

    private_message_handler = MessageHandler(
        ((filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.ALL) & filters.ChatType.PRIVATE) & ~filters.COMMAND,
        message_handler.handle_message
    )
    mentioned_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.ALL)
        & filters.ChatType.GROUPS
        & (filters.Entity("mention") | filters.CaptionEntity("mention")),
        message_handler.handle_message
    )
    reply_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.ALL)
        & filters.ChatType.GROUPS
        & filters.REPLY,
        message_handler.handle_message
    )

    clear_history_handler = TgCommandHandler(["clear", "c"], command_handler.clear_history_command)
    resend_voice_handler = TgCommandHandler(["voice_last", "v"], command_handler.resend_last_as_voice_command)
    stats_handler = TgCommandHandler(["stats", "s"], command_handler.stats_command)
    audio_handler = TgCommandHandler(["audio", "a"], command_handler.audio_command)
    show_files_handler = TgCommandHandler(["showfiles"], command_handler.show_files_command)
    remove_file_handler = TgCommandHandler(["removefile"], command_handler.remove_file_command)
    clear_files_handler = TgCommandHandler(["clearfiles"], command_handler.clear_files_command)

    app.add_handler(private_message_handler)
    app.add_handler(mentioned_message_handler)
    app.add_handler(reply_message_handler)
    app.add_handler(clear_history_handler)
    app.add_handler(resend_voice_handler)
    app.add_handler(stats_handler)
    app.add_handler(audio_handler)
    app.add_handler(show_files_handler)
    app.add_handler(remove_file_handler)
    app.add_handler(clear_files_handler)

    app.run_polling()
