# src/message_handler.py

from telegram import Update
from telegram.ext import ContextTypes
from src.message_wrapper import MessageWrapper
from src.heroku_config_parser import ConfigReader
from src.voice_processor import VoiceProcessor
from src.chat_history_manager import ChatHistoryManager
from src.openai_wrapper import OpenAIRealtimeClient

class CustomMessageHandler:
    def __init__(self, config: ConfigReader, voice_processor: VoiceProcessor, chat_history_manager: ChatHistoryManager):
        self.config = config
        self.voice_processor = voice_processor
        self.chat_history_manager = chat_history_manager
        self.authenticated_users = {}
        self.openai_client = OpenAIRealtimeClient(api_key=config.get_openai_settings()['api_key'])

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        message_text = update.message.text if update.message.text else ""

        if not await self._should_process_message(context.bot, MessageWrapper(update)):
            print("Повідомлення не оброблено через фільтр.")
            return

        if not self.authenticated_users.get(chat_id):
            if message_text == self.config.get_system_messages().get('password') or self.config.get_system_messages().get('password') == "":
                self.authenticated_users[chat_id] = True
                await update.message.reply_text("Автентифікація успішна. Ви можете почати спілкування.")
            else:
                await update.message.reply_text("Будь ласка, введіть пароль для продовження.")
            return

        try:
            wrapped_message = MessageWrapper(update)
            await self._handle_user_message(context.bot, wrapped_message)
        except Exception as e:
            print(f"Помилка при обробці повідомлення: {e}")

    async def _should_process_message(self, bot, message):
        bot_username = (await bot.get_me()).username
        return (
            message.chat_type == 'private' or
            (message.text and f"@{bot_username}" in message.text) or
            (message.reply_to_message and message.reply_to_message_from_user_username == bot_username)
        )

    async def _handle_user_message(self, bot, message: MessageWrapper):
        user_message, is_voice = await self._process_message_content(message)
        if user_message is None:
            print("Повідомлення користувача не знайдено.")
            return

        first_name = message.from_user_first_name
        chat_id = message.chat_id
        print(f"Обробка повідомлення від {first_name} ({chat_id})")

        await self.openai_client.connect()

        if is_voice:
            await self.openai_client.send_audio(user_message)
        else:
            await self.openai_client.send_message(user_message)

        # Отримуємо та відправляємо відповідь користувачу
        response_text = await self.openai_client.receive_responses()
        await message.reply_text(response_text)

        await self.openai_client.close()

    async def _process_message_content(self, message):
        is_voice = False

        if message.voice:
            print("Отримано голосове повідомлення")
            voice_message_path = await message.download_voice()
            encoded_audio = self.voice_processor.encode_audio_to_base64(voice_message_path)
            return encoded_audio, True
        elif message.text:
            return message.text, False
        else:
            return None, False
