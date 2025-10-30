# main.py
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler

from src.aisus.chat_history_manager import ChatHistoryManager
from src.aisus.config_parser import ConfigReader
from src.aisus.message_handler import CustomMessageHandler
from src.aisus.openai_wrapper import OpenAIWrapper

if __name__ == "__main__":
    config = ConfigReader()

    openai_settings = config.get_openai_settings()
    deepseek_settings = config.get_deepseek_settings()

    chat_history_manager = ChatHistoryManager()
    openai_wrapper = OpenAIWrapper(
        api_key=openai_settings["api_key"],
        api_mode=openai_settings["api_mode"],
        reasoning_effort=openai_settings["reasoning_effort"],
        search_enabled=str(openai_settings["search_enabled"]).lower() in ("1", "true", "yes"),
        web_search_enabled=str(openai_settings["web_search_enabled"]).lower() in ("1", "true", "yes"),
        whisper_model=openai_settings["whisper_model"],
        tts_model=openai_settings["tts_model"],
        base_url=openai_settings["base_url"],
    )

    chat_wrapper = openai_wrapper
    chat_model = openai_settings["gpt_model"]

    if deepseek_settings["api_key"]:
        chat_wrapper = OpenAIWrapper(
            api_key=deepseek_settings["api_key"],
            api_mode=deepseek_settings.get("api_mode") or "chat_completions",
            base_url=deepseek_settings.get("base_url"),
        )
        chat_model = deepseek_settings.get("model") or chat_model

    if openai_settings["search_enabled"]:
        openai_wrapper.restore_vector_stores()

    message_handler = CustomMessageHandler(
        config,
        chat_history_manager,
        openai_wrapper,
        chat_wrapper=chat_wrapper,
        chat_model=chat_model,
    )

    app = ApplicationBuilder().token(config.get_api_settings()["bot_token"]).build()

    private_message_handler = MessageHandler(
        ((filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.ALL) & filters.ChatType.PRIVATE) & ~filters.COMMAND,
        message_handler.handle_message,
    )
    mentioned_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.ALL)
        & filters.ChatType.GROUPS
        & (filters.Entity("mention") | filters.CaptionEntity("mention")),
        message_handler.handle_message,
    )
    reply_message_handler = MessageHandler(
        (filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.ALL)
        & filters.ChatType.GROUPS
        & filters.REPLY,
        message_handler.handle_message,
    )

    clear_history_handler = CommandHandler(["clear", "c"], message_handler.clear_history_command)
    resend_voice_handler = CommandHandler(["voice_last", "v"], message_handler.resend_last_as_voice_command)
    stats_handler = CommandHandler(["stats", "s"], message_handler.stats_command)
    audio_handler = CommandHandler(["audio", "a"], message_handler.audio_command)
    show_files_handler = CommandHandler(["showfiles"], message_handler.show_files_command)
    remove_file_handler = CommandHandler(["removefile"], message_handler.remove_file_command)
    clear_files_handler = CommandHandler(["clearfiles"], message_handler.clear_files_command)

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
