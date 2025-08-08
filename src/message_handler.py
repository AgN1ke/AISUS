#message_handler.py

import os
import requests
from telegram import Update
from telegram.ext import ContextTypes
from src.message_wrapper import MessageWrapper
from src.heroku_config_parser import ConfigReader
from src.voice_processor import VoiceProcessor
from src.chat_history_manager import ChatHistoryManager
from src.openai_wrapper import OpenAIWrapper
import base64

class CustomMessageHandler:
    def __init__(self, config: ConfigReader, voice_processor: VoiceProcessor, chat_history_manager: ChatHistoryManager, openai_wrapper: OpenAIWrapper):
        self.config = config
        self.voice_processor = voice_processor
        self.chat_history_manager = chat_history_manager
        self.openai_wrapper = openai_wrapper
        self.authenticated_users = {}  # Dictionary to keep track of authenticated users

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        message_text = update.message.text if update.message.text else ""

        # Перевірка, чи бот має бути активований в публічному чаті (тільки через тег або відповідь)
        if not await self._should_process_message(context.bot, MessageWrapper(update)):
            print("Message not processed due to filter.")
            return

        # Check if the user is already authenticated
        if not self.authenticated_users.get(chat_id):
            if message_text == self.config.get_system_messages().get('password') or self.config.get_system_messages().get('password') == "":
                # Authenticate the user if the password is correct
                self.authenticated_users[chat_id] = True
                await update.message.reply_text("Автентифікація успішна. Ви можете почати спілкування.")
            else:
                # Ask for the password if the user is not authenticated
                await update.message.reply_text("Будь ласка, введіть пароль для продовження.")
            return  # Exit here if not authenticated or after successful authentication

        try:
            wrapped_message = MessageWrapper(update)
            await self._handle_user_message(context.bot, wrapped_message)
        except Exception as e:
            print(f"Error handling message: {e}")

    async def _should_process_message(self, bot, message):
        """Determine if the message should be processed."""
        bot_username = (await bot.get_me()).username
        # Only process the message if it's a private chat or the bot is mentioned/replied to
        return (
            message.chat_type == 'private' or
            (message.text and f"@{bot_username}" in message.text) or
            (message.reply_to_message and message.reply_to_message_from_user_username == bot_username)
        )

    async def _handle_user_message(self, bot, message: MessageWrapper):
        """Handle incoming user messages (text, voice, image) and generate responses."""
        user_message, is_voice, is_image = await self._process_message_content(message)
        if user_message is None:
            print("No user message found.")
            return

        first_name, last_name = message.from_user_first_name, message.from_user_last_name
        chat_id = message.chat_id

        if is_voice:
            # Transcribe the user's voice for context
            transcribed_text = await self.voice_processor.transcribe_voice_message(user_message)
            print(f"Processing voice message from {first_name} {last_name} ({chat_id}): {transcribed_text}")
            self._update_chat_history(chat_id, first_name, transcribed_text, True, False)

            # Generate voice response from OpenAI
            voice_response = await self.voice_processor.voice_to_voice_chat(
                user_message,
                self.config.get_openai_settings()['gpt_model'],
                self.config.get_openai_settings()['vocalizer_voice'],
                self.config.get_file_paths_and_limits()['audio_folder_path'],
            )

            if voice_response:
                await self._send_response(message, voice_response, True)
                # Transcribe bot response and store it
                bot_text = await self.voice_processor.transcribe_voice_message(voice_response)
                self.chat_history_manager.add_bot_message(chat_id, bot_text)

            if os.path.exists(user_message):
                try:
                    os.remove(user_message)
                except Exception as e:
                    print(f"Error removing temp voice file {user_message}: {e}")

            self.chat_history_manager.prune_history(chat_id, 124000)
            return

        print(f"Processing message from {first_name} {last_name} ({chat_id}): {user_message}")
        self._update_chat_history(chat_id, first_name, user_message, is_voice, is_image)

        try:
            bot_response = self._generate_bot_response(chat_id)
            print(f"Generated response: {bot_response}")
            await self._send_response(message, bot_response, False)
            self.chat_history_manager.add_bot_message(chat_id, bot_response)
        except Exception as e:
            print(f"Error generating or sending response: {e}")
            await message.reply_text("Вибачте, але я не можу продовжити цю розмову.")

        self.chat_history_manager.prune_history(chat_id, 124000)

    async def _process_message_content(self, message):
        """Process the content of the message, whether it's text, voice, or image."""
        is_voice = False
        is_image = False

        if message.voice:
            print("Voice file received")
            voice_message_path = await message.download_voice()
            return voice_message_path, True, False
        elif message.photo:
            print("Image received")
            image_path = await message.download_image()
            # Get image caption
            image_caption = message.message.caption or " "
            # Analyze image with OpenAI
            analysis_result = await self._analyze_image_with_openai(image_path)
            # Form the full message combining all elements
            full_image_message = f"{self.config.get_system_messages()['image_message_affix']} " \
                                 f"{self.config.get_system_messages()['image_caption_affix']} {image_caption} " \
                                 f"{self.config.get_system_messages()['image_sence_affix']} {analysis_result}"
            return full_image_message, False, True
        else:
            return message.text, False, False

    async def _analyze_image_with_openai(self, image_path: str) -> str:
        """Send image to OpenAI for analysis and return the result."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.get_openai_settings()['api_key']}"
        }

        # Read the image and encode it in base64
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What's in this image?"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 900
        }

        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        return response.json()["choices"][0]["message"]["content"]

    def _update_chat_history(self, chat_id, first_name, user_message, is_voice, is_image):
        """Update the chat history with the user's message."""
        self.chat_history_manager.add_system_message(chat_id, self.config.get_system_messages()['welcome_message'])

        if is_voice:
            self.chat_history_manager.add_system_voice_affix_if_not_exist(
                chat_id, self.config.get_system_messages()['voice_message_affix'])
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)
        elif is_image:
            # Since we are directly receiving the combined message for images, just add it
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)
        else:
            self.chat_history_manager.remove_system_voice_affix_if_exist(
                chat_id, self.config.get_system_messages()['voice_message_affix'])
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)

    def _generate_bot_response(self, chat_id):
        """Generate the bot's response using OpenAI."""
        response = self.openai_wrapper.chat_completion(
            model=self.config.get_openai_settings()['gpt_model'],
            messages=self.chat_history_manager.get_history(chat_id),
            max_tokens=3000)  # Обеспечиваем лимит для ответа в 4000 токенов
        bot_response = response.choices[0].message.content
        return bot_response

    async def _send_response(self, message, bot_response, is_voice):
        """Send the response back to the user."""
        if is_voice:
            await message.reply_voice(bot_response)
            if os.path.exists(bot_response):
                os.remove(bot_response)
        else:
            await message.reply_text(bot_response)
