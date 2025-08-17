# message_handler.py
import os
import base64
import logging
from typing import Tuple, Optional, Dict, Any
import requests
from telegram import Update, Bot
from telegram.ext import CallbackContext
from src.aisus.message_wrapper import MessageWrapper
from src.aisus.config_parser import ConfigReader
from src.aisus.voice_processor import VoiceProcessor
from src.aisus.chat_history_manager import ChatHistoryManager
from src.aisus.openai_wrapper import OpenAIWrapper
import time

logger: logging.Logger = logging.getLogger(__name__)


class CustomMessageHandler:
    def __init__(self, config: ConfigReader, voice_processor: VoiceProcessor, chat_history_manager: ChatHistoryManager,
                 openai_wrapper: OpenAIWrapper) -> None:
        self.config: ConfigReader = config
        self.voice_processor: VoiceProcessor = voice_processor
        self.chat_history_manager: ChatHistoryManager = chat_history_manager
        self.openai_wrapper: OpenAIWrapper = openai_wrapper
        self.authenticated_users: Dict[int, bool] = {}
        self.started_at = time.monotonic()
        self.tokens_in = 0
        self.tokens_out = 0
        self.messages_in = 0
        self.messages_out = 0
        self.per_message_stats = []

    async def handle_message(self, update: Update, context: CallbackContext) -> None:
        chat_id: int = update.effective_chat.id
        bot_username: str = (await context.bot.get_me()).username
        raw_text: str = (update.message.text or update.message.caption or "")
        message_text_for_auth: str = raw_text.replace(f"@{bot_username}", "").strip()
        if not await self._should_process_message(context.bot, MessageWrapper(update)):
            return
        if not self.authenticated_users.get(chat_id):
            password: str = self.config.get_system_messages().get("password", "")
            if message_text_for_auth == password or password == "":
                self.authenticated_users[chat_id] = True
                await update.message.reply_text("Автентифікація успішна. Ви можете почати спілкування.")
            else:
                await update.message.reply_text("Будь ласка, введіть пароль для продовження.")
            return
        try:
            wrapped_message: MessageWrapper = MessageWrapper(update)
            await self._handle_user_message(wrapped_message)
        except Exception as exc:
            logger.exception("handle_message failed: %s", exc)
            try:
                await update.message.reply_text("Сталася помилка. Спробуйте ще раз.")
            except Exception as notify_exc:
                logger.exception("failed to notify user: %s", notify_exc)

    @staticmethod
    async def _should_process_message(bot: Bot, message: MessageWrapper) -> bool:
        bot_username: str = (await bot.get_me()).username
        is_private_chat: bool = getattr(message, "chat_type", None) == "private"
        text_attr: Any = getattr(message, "text", None)
        caption_attr: Any = getattr(message, "caption", None)
        text_content: str = text_attr if isinstance(text_attr, str) else ""
        caption_text: str = caption_attr if isinstance(caption_attr, str) else ""
        has_mention: bool = (f"@{bot_username}" in text_content) or (f"@{bot_username}" in caption_text)
        is_reply_to_bot: bool = bool(
            getattr(message, "reply_to_message", None)
            and getattr(message, "reply_to_message_from_user_username", None) == bot_username
        )
        return is_private_chat or has_mention or is_reply_to_bot

    async def _handle_user_message(self, message: MessageWrapper) -> None:
        user_message, is_voice, is_image = await self._process_message_content(message)
        if not user_message:
            return
        self.messages_in += 1
        first_name = message.from_user_first_name
        chat_id = message.chat_id
        self._update_chat_history(chat_id, first_name, user_message, is_voice, is_image)
        try:
            bot_response = self._generate_bot_response(chat_id)
            await self._send_response(message, bot_response, is_voice)
            self.chat_history_manager.add_bot_message(chat_id, bot_response)
            self.messages_out += 1
        except Exception as exc:
            logger.exception("response generation/sending failed: %s", exc)
            try:
                await message.reply_text("Сталася помилка. Спробуйте ще раз.")
            except Exception as notify_exc:
                logger.exception("failed to notify user: %s", notify_exc)
        max_history_length = self.config.get_file_paths_and_limits()["max_history_length"]
        self.chat_history_manager.prune_history(chat_id, max_history_length)

    async def _process_message_content(self, message: MessageWrapper) -> Tuple[Optional[str], bool, bool]:
        paths_and_limits: Dict[str, Any] = self.config.get_file_paths_and_limits()
        audio_dir: Optional[str] = paths_and_limits.get("audio_folder_path")
        image_dir: Optional[str] = paths_and_limits.get("image_folder_path") or audio_dir
        if message.voice:
            if not audio_dir:
                return None, False, False
            voice_message_path: Optional[str] = None
            try:
                voice_message_path = await message.download_voice(audio_dir)
                transcribed_text: str = self.voice_processor.transcribe_voice_message(voice_message_path)
                return transcribed_text, True, False
            finally:
                if voice_message_path and os.path.exists(voice_message_path):
                    try:
                        os.remove(voice_message_path)
                    except OSError as exc:
                        logger.exception("failed to remove temp voice file: %s", exc)
        if message.photo:
            if not image_dir:
                return None, False, False
            image_path: Optional[str] = None
            try:
                image_path = await message.download_image(image_dir)
                image_caption: str = message.message.caption or " "
                analysis_result: str = await self._analyze_image_with_openai(image_path)
                full_image_message: str = (
                    f"{self.config.get_system_messages()['image_message_affix']} "
                    f"{self.config.get_system_messages()['image_caption_affix']} {image_caption} "
                    f"{self.config.get_system_messages()['image_sence_affix']} {analysis_result}"
                )
                return full_image_message, False, True
            finally:
                if image_path and os.path.exists(image_path):
                    try:
                        os.remove(image_path)
                    except OSError as exc:
                        logger.exception("failed to remove temp image file: %s", exc)
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
        self.chat_history_manager.add_system_message(chat_id, self.config.get_system_messages()["gpt_prompt"])
        if is_voice:
            self.chat_history_manager.add_system_voice_affix_if_not_exist(
                chat_id, self.config.get_system_messages()["voice_message_affix"]
            )
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)
            return
        if is_image:
            self.chat_history_manager.add_user_message(chat_id, first_name, user_message)
            return
        self.chat_history_manager.remove_system_voice_affix_if_exist(
            chat_id, self.config.get_system_messages()["voice_message_affix"]
        )
        self.chat_history_manager.add_user_message(chat_id, first_name, user_message)

    def _generate_bot_response(self, chat_id: int) -> str:
        response_tokens_limit = self.config.get_file_paths_and_limits()["max_tokens"]
        response = self.openai_wrapper.generate(
            model=self.config.get_openai_settings()["gpt_model"],
            messages=self.chat_history_manager.get_history(chat_id),
            max_tokens=response_tokens_limit,
        )

        ti = to = 0
        extract_usage = getattr(self.openai_wrapper, "extract_usage", None)
        if callable(extract_usage):
            try:
                ti, to = extract_usage(response) or (0, 0)
                ti = int(ti or 0)
                to = int(to or 0)
            except (TypeError, AttributeError, ValueError):
                ti = to = 0

        self.tokens_in += ti
        self.tokens_out += to
        self.per_message_stats.append({
            "chat_id": chat_id,
            "tokens_in": ti,
            "tokens_out": to,
            "tokens_total": ti + to
        })

        return self.openai_wrapper.extract_text(response)

    async def _send_response(self, message: MessageWrapper, bot_response: str, is_voice: bool) -> None:
        if is_voice:
            audio_dir_opt: Optional[str] = self.config.get_file_paths_and_limits().get("audio_folder_path")
            if audio_dir_opt:
                os.makedirs(audio_dir_opt, exist_ok=True)
            voice_response_file: str = self.voice_processor.generate_voice_response_and_save_file(
                bot_response,
                self.config.get_openai_settings()["vocalizer_voice"],
                audio_dir_opt or ""
            )
            await message.reply_voice(voice_response_file)
            if os.path.exists(voice_response_file):
                try:
                    os.remove(voice_response_file)
                except OSError as exc:
                    logger.exception("failed to remove temp tts file: %s", exc)
            return
        await message.reply_text(bot_response)

    async def clear_history_command(self, update: Update, context: CallbackContext) -> None:
        chat_id: int = update.effective_chat.id
        self.chat_history_manager.clear_history(chat_id)
        await update.message.reply_text("Історію чату очищено.")

    async def resend_last_as_voice_command(self, update: Update, context: CallbackContext) -> None:
        chat_id: int = update.effective_chat.id
        history = self.chat_history_manager.get_history(chat_id)

        last_bot_text: Optional[str] = None
        for entry in reversed(history):
            role: str = str(entry.get("role", ""))
            content: Any = entry.get("content", "")
            if role == "assistant" and isinstance(content, str) and content.strip():
                last_bot_text = content
                break

        if not last_bot_text:
            await update.message.reply_text("Немає попереднього повідомлення бота для цього чату.")
            return

        audio_dir_opt: Optional[str] = self.config.get_file_paths_and_limits().get("audio_folder_path")
        if audio_dir_opt:
            os.makedirs(audio_dir_opt, exist_ok=True)

        voice_file: str = self.voice_processor.generate_voice_response_and_save_file(
            last_bot_text,
            self.config.get_openai_settings()["vocalizer_voice"],
            audio_dir_opt or ""
        )
        await update.message.reply_voice(voice_file)
        if os.path.exists(voice_file):
            try:
                os.remove(voice_file)
            except OSError as exc:
                logger.exception("failed to remove temp tts file: %s", exc)

    def get_stats(self) -> Dict[str, Any]:
        total_messages = max(1, self.messages_out)  # avoid div/0
        avg_in = self.tokens_in // total_messages
        avg_out = self.tokens_out // total_messages
        return {
            "uptime_seconds": int(time.monotonic() - self.started_at),
            "messages_in": self.messages_in,
            "messages_out": self.messages_out,
            "total_tokens_in": self.tokens_in,
            "total_tokens_out": self.tokens_out,
            "avg_tokens_in_per_message": avg_in,
            "avg_tokens_out_per_message": avg_out,
        }

    async def stats_command(self, update: Update, context: CallbackContext) -> None:
        s = self.get_stats()
        secs = s["uptime_seconds"]
        h, m, sec = secs // 3600, (secs % 3600) // 60, secs % 60
        lines = [
            f"uptime: {h:02d}:{m:02d}:{sec:02d}",
            f"messages in: {s['messages_in']}",
            f"messages out: {s['messages_out']}",
            f"tokens in: {s['total_tokens_in']} (avg {s['avg_tokens_in_per_message']})",
            f"tokens out: {s['total_tokens_out']} (avg {s['avg_tokens_out_per_message']})",
        ]
        await update.message.reply_text("\n".join(lines))
