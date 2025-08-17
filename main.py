# main.py

from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler

from src.aisus.chat_history_manager import ChatHistoryManager
from src.aisus.config_parser import ConfigReader
from src.aisus.message_handler import CustomMessageHandler
from src.aisus.openai_wrapper import OpenAIWrapper
from src.aisus.voice_processor import VoiceProcessor

if __name__ == "__main__":
    config = ConfigReader()

    voice_processor = VoiceProcessor(api_key=config.get_openai_settings()['api_key'],
                                     whisper_model=config.get_openai_settings()['whisper_model'],
                                     tts_model=config.get_openai_settings()['tts_model'])
    chat_history_manager = ChatHistoryManager()
    openai_wrapper = OpenAIWrapper(config.get_openai_settings()['api_key'])
    message_handler = CustomMessageHandler(config, voice_processor, chat_history_manager, openai_wrapper)

    app = ApplicationBuilder().token(config.get_api_settings()['bot_token']).build()

    private_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO) & filters.ChatType.PRIVATE,
        message_handler.handle_message)

    mentioned_message_handler: MessageHandler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO)
        & filters.ChatType.GROUPS
        & (filters.Entity("mention") | filters.CaptionEntity("mention")),
        message_handler.handle_message)

    reply_message_handler: MessageHandler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO) & filters.ChatType.GROUPS & filters.REPLY,
        message_handler.handle_message)

    clear_history_handler: CommandHandler = (
        CommandHandler(["clear", "c"], message_handler.clear_history_command))

    resend_voice_handler: CommandHandler = (
        CommandHandler(["voice_last", "v"], message_handler.resend_last_as_voice_command))

    stats_handler: CommandHandler = CommandHandler(["stats", "s"], message_handler.stats_command)

    app.add_handler(private_message_handler)
    app.add_handler(mentioned_message_handler)
    app.add_handler(reply_message_handler)
    app.add_handler(clear_history_handler)
    app.add_handler(resend_voice_handler)
    app.add_handler(stats_handler)

    app.run_polling()
