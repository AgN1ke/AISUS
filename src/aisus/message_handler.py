# message_handler.py
import os
import base64
from typing import Tuple, Optional, Dict, Any
import requests
from telegram import Update
from telegram.ext import CallbackContext
from src.aisus.message_wrapper import MessageWrapper
from src.aisus.config_parser import ConfigReader
from src.aisus.voice_processor import VoiceProcessor
from src.aisus.chat_history_manager import ChatHistoryManager
from src.aisus.openai_wrapper import OpenAIWrapper


class CustomMessageHandler:
    def __init__(self, config: ConfigReader, voice_processor: VoiceProcessor, chat_history_manager: ChatHistoryManager,
                 openai_wrapper: OpenAIWrapper) -> None:
        self.config: ConfigReader = config
        self.voice_processor: VoiceProcessor = voice_processor
        self.chat_history_manager: ChatHistoryManager = chat_history_manager
        self.openai_wrapper: OpenAIWrapper = openai_wrapper
        self.authenticated_users: Dict[int, bool] = {}

    async def handle_message(self, update: Update, context: CallbackContext) -> None:
        chat_id: int = update.effective_chat.id
        message_text: str = update.message.text if update.message and update.message.text else ""
        if not await self._should_process_message(context.bot, MessageWrapper(update)):
            return
        if not self.authenticated_users.get(chat_id):
            if message_text == self.config.get_system_messages().get(
                    "password") or self.config.get_system_messages().get("password") == "":
                self.authenticated_users[chat_id] = True
                await update.message.reply_text("Автентифікація успішна. Ви можете почати спілкування.")
            else:
                await update.message.reply_text("Будь ласка, введіть пароль для продовження.")
            return
        try:
            wrapped_message: MessageWrapper = MessageWrapper(update)
            await self._handle_user_message(wrapped_message)
        except Exception as e:
            print(f"Error handling message: {e}")

    @staticmethod
    async def _should_process_message(bot: Any, message: MessageWrapper) -> bool:
        bot_username: str = (await bot.get_me()).username
        return (
                message.chat_type == "private" or
                (message.text and f"@{bot_username}" in message.text) or
                (message.reply_to_message and message.reply_to_message_from_user_username == bot_username)
        )

    async def _handle_user_message(self, message: MessageWrapper) -> None:
        user_message, is_voice, is_image = await self._process_message_content(message)
        if not user_message:
            return
        first_name: str = message.from_user_first_name
        chat_id: int = message.chat_id
        self._update_chat_history(chat_id, first_name, user_message, is_voice, is_image)
        try:
            bot_response: str = self._generate_bot_response(chat_id)
            await self._send_response(message, bot_response, is_voice)
            self.chat_history_manager.add_bot_message(chat_id, bot_response)
        except Exception as e:
            print(f"Error generating or sending response: {e}")
            await message.reply_text("Вибачте, але я не можу продовжити цю розмову.")
        max_history_length: int = self.config.get_file_paths_and_limits()["max_history_length"]
        self.chat_history_manager.prune_history(chat_id, max_history_length)

    async def _process_message_content(self, message: MessageWrapper) -> Tuple[Optional[str], bool, bool]:
        if message.voice:
            voice_message_path: str = await message.download_voice()
            transcribed_text: str = self.voice_processor.transcribe_voice_message(voice_message_path)
            return transcribed_text, True, False
        if message.photo:
            image_path: str = await message.download_image()
            image_caption: str = message.message.caption or " "
            analysis_result: str = await self._analyze_image_with_openai(image_path)
            full_image_message: str = f"{self.config.get_system_messages()['image_message_affix']} {self.config.get_system_messages()['image_caption_affix']} {image_caption} {self.config.get_system_messages()['image_sence_affix']} {analysis_result}"
            return full_image_message, False, True
        return message.text, False, False

    async def _analyze_image_with_openai(self, image_path: str) -> str:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.get_openai_settings()['api_key']}"
        }
        with open(image_path, "rb") as image_file:
            base64_image: str = base64.b64encode(image_file.read()).decode("utf-8")
        response_tokens_limit: int = self.config.get_file_paths_and_limits()["max_tokens"]
        payload: Dict[str, Any] = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What's in this image?"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            "max_tokens": response_tokens_limit
        }
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        return response.json()["choices"][0]["message"]["content"]

    def _update_chat_history(self, chat_id: int, first_name: str, user_message: str, is_voice: bool,
                             is_image: bool) -> None:
        self.chat_history_manager.add_system_message(chat_id, self.config.get_system_messages()["welcome_message"])
        if is_voice:
            self.chat_history_manager.add_system_voice_affix_if_not_exist(chat_id, self.config.get_system_messages()[
                "voice_message_affix"])
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)
            return
        if is_image:
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)
            return
        self.chat_history_manager.remove_system_voice_affix_if_exist(chat_id, self.config.get_system_messages()[
            "voice_message_affix"])
        self.chat_history_manager.add_user_message(chat_id, first_name, user_message)

    def _generate_bot_response(self, chat_id: int) -> str:
        response_tokens_limit: int = self.config.get_file_paths_and_limits()["max_tokens"]
        response = self.openai_wrapper.chat_completion(
            model=self.config.get_openai_settings()["gpt_model"],
            messages=self.chat_history_manager.get_history(chat_id),
            max_tokens=response_tokens_limit
        )
        bot_response: str = response.choices[0].message.content
        return bot_response

    async def _send_response(self, message: MessageWrapper, bot_response: str, is_voice: bool) -> None:
        if is_voice:
            voice_response_file: str = self.voice_processor.generate_voice_response_and_save_file(
                bot_response,
                self.config.get_openai_settings()["vocalizer_voice"],
                self.config.get_file_paths_and_limits()["audio_folder_path"]
            )
            await message.reply_voice(voice_response_file)
            if os.path.exists(voice_response_file):
                os.remove(voice_response_file)
            return
        await message.reply_text(bot_response)
