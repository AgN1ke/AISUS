import os
from telegram import Update
from telegram.ext import ContextTypes
from src.message_wrapper import MessageWrapper
from src.config_reader import ConfigReader
from src.voice_processor import VoiceProcessor
from src.chat_history_manager import ChatHistoryManager
from src.openai_wrapper import OpenAIWrapper

class CustomMessageHandler:
    def __init__(self, config: ConfigReader, voice_processor: VoiceProcessor, chat_history_manager: ChatHistoryManager, openai_wrapper: OpenAIWrapper):
        self.config = config
        self.voice_processor = voice_processor
        self.chat_history_manager = chat_history_manager
        self.openai_wrapper = openai_wrapper
        self.authenticated_users = {}  # Dictionary to keep track of authenticated users

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        message_text = update.message.text

        # Перевірка, чи бот має бути активований в публічному чаті (тільки через тег або відповідь)
        if not await self._should_process_message(context.bot, MessageWrapper(update)):
            print("Message not processed due to filter.")
            return

        # Check if the user is already authenticated
        if not self.authenticated_users.get(chat_id):
            if message_text == self.config.get_system_messages().get('password'):
                # Authenticate the user if the password is correct
                self.authenticated_users[chat_id] = True
                await update.message.reply_text("Автентифікація успішна. Ви можете почати спілкування.")
            else:
                # Ask for the password if the user is not authenticated
                await update.message.reply_text("Будь ласка, введіть пароль для продовження.")
            return  # Exit here if not authenticated or after successful authentication

        # Process the message if the user is authenticated
        try:
            wrapped_message = MessageWrapper(update)
            await self._handle_message(context.bot, wrapped_message)
        except Exception as e:
            print(f"Error handling message: {e}")
            await update.message.reply_text("Сталася помилка при обробці вашого повідомлення.")

    async def _should_process_message(self, bot, message):
        """Determine if the message should be processed."""
        bot_username = (await bot.get_me()).username
        # Only process the message if it's a private chat or the bot is mentioned/replied to
        return (
            message.chat_type == 'private' or
            (message.text and f"@{bot_username}" in message.text) or
            (message.reply_to_message and message.reply_to_message_from_user_username == bot_username)
        )

    async def _handle_message(self, bot, message: MessageWrapper):
        """Handle incoming messages and generate responses."""
        user_message, is_voice = await self._process_message_content(message)
        if not user_message:
            print("No user message found.")
            return

        first_name, last_name = message.from_user_first_name, message.from_user_last_name
        chat_id = message.chat_id
        print(f"Processing message from {first_name} {last_name} ({chat_id}): {user_message}")
        self._update_chat_history(chat_id, first_name, user_message, is_voice)

        try:
            bot_response = self._generate_bot_response(chat_id)
            print(f"Generated response: {bot_response}")
            await self._send_response(message, bot_response, is_voice)
            self.chat_history_manager.add_bot_message(chat_id, bot_response)
        except Exception as e:
            print(f"Error generating or sending response: {e}")
            await message.reply_text("Вибачте, але я не можу продовжити цю розмову.")

        self.chat_history_manager.prune_history(chat_id, 124000)

    async def _process_message_content(self, message):
        """Process the content of the message, whether it's voice or text."""
        if message.voice:
            print("Voice file received")
            voice_message_path = await message.download()
            transcribed_text = self.voice_processor.transcribe_voice_message(voice_message_path)
            print(f"Voice message: {transcribed_text}")
            return transcribed_text, True
        else:
            return message.text, False

    def _update_chat_history(self, chat_id, first_name, user_message, is_voice):
        """Update the chat history with the user's message."""
        self.chat_history_manager.add_system_message(chat_id, self.config.get_system_messages()['welcome_message'])
        if is_voice:
            self.chat_history_manager.add_system_voice_affix_if_not_exist(
                chat_id, self.config.get_system_messages()['voice_message_affix'])
        else:
            self.chat_history_manager.remove_system_voice_affix_if_exist(
                chat_id, self.config.get_system_messages()['voice_message_affix'])
        self.chat_history_manager.add_user_message(chat_id, first_name, user_message)

    def _generate_bot_response(self, chat_id):
        """Generate the bot's response using OpenAI."""
        try:
            response = self.openai_wrapper.chat_completion(
                model=self.config.get_openai_settings()['gpt_model'],
                messages=self.chat_history_manager.get_history(chat_id),
                max_tokens=4000
            )
            bot_response = response.choices[0].message.content
            print(f"Bot response: {bot_response}")
            return bot_response
        except Exception as e:
            print(f"Error generating bot response: {e}")
            return "Вибачте, але я не можу продовжити цю розмову."

    async def _send_response(self, message, bot_response, is_voice):
        """Send the response back to the user."""
        try:
            if is_voice:
                voice_response_file = self.voice_processor.generate_voice_response_and_save_file(
                    bot_response,
                    self.config.get_openai_settings()['vocalizer_voice'],
                    self.config.get_file_paths_and_limits()['audio_folder_path']
                )
                await message.reply_voice(voice_response_file)
                if os.path.exists(voice_response_file):
                    os.remove(voice_response_file)
            else:
                # Додаємо parse_mode для форматування Markdown
                await message.reply_text(bot_response, parse_mode="Markdown")
        except Exception as e:
            print(f"Error sending response: {e}")
            await message.reply_text("Сталася помилка при відправці відповіді.")
