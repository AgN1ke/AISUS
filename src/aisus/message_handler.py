# message_handler.py
import os
import base64
import logging
from typing import Tuple, Optional, Dict, Any
import requests
from telegram import Update
from telegram.ext import CallbackContext
from src.aisus.message_wrapper import MessageWrapper
from src.aisus.config_parser import ConfigReader
from src.aisus.voice_processor import VoiceProcessor
from src.aisus.chat_history_manager import ChatHistoryManager
from src.aisus.openai_wrapper import OpenAIWrapper
import inspect
from src.aisus.handlers.message_router import MessageRouter
from src.aisus.services.auth import AuthService
from src.aisus.services.stats import StatsService

logger: logging.Logger = logging.getLogger(__name__)


class CustomMessageHandler:
    def __init__(
        self,
        config: ConfigReader,
        voice_processor: VoiceProcessor,
        chat_history_manager: ChatHistoryManager,
        openai_wrapper: OpenAIWrapper,
        message_router: MessageRouter,
        auth_service: AuthService,
        stats: StatsService,
    ) -> None:
        self.config = config
        self.voice_processor = voice_processor
        self.chat_history_manager = chat_history_manager
        self.openai_wrapper = openai_wrapper
        self.message_router = message_router
        self.auth = auth_service
        self.stats = stats

    async def handle_message(self, update: Update, context: CallbackContext) -> None:
        if not await self.message_router.should_process(context.bot, MessageWrapper(update)):
            return
        bot_username: str = (await context.bot.get_me()).username
        if not await self.auth.authenticate(update, bot_username):
            return
        try:
            wrapped_message = MessageWrapper(update)
            await self._handle_user_message(wrapped_message)
        except Exception as exc:
            logger.exception("handle_message failed: %s", exc)
            try:
                await update.message.reply_text("Сталася помилка. Спробуйте ще раз.")
            except Exception as notify_exc:
                logger.exception("failed to notify user: %s", notify_exc)

    async def _handle_user_message(self, message: MessageWrapper) -> None:
        user_message, is_voice, is_image = await self._process_message_content(message)
        if not user_message:
            return
        self.stats.record_incoming()
        first_name = message.from_user_first_name
        chat_id = message.chat_id

        history = self.chat_history_manager.get_history(chat_id)
        if not history or history[0].get("role") != "system":
            self.chat_history_manager.add_system_message(
                chat_id, self.config.get_system_messages().get("gpt_prompt", "")
            )

        self._update_chat_history(chat_id, first_name, user_message, is_voice, is_image)

        try:
            bot_response, used_fs, ti, to = await self._generate_bot_response(chat_id)
            await self._send_response(message, bot_response, is_voice, used_fs)
            self.chat_history_manager.add_bot_message(chat_id, bot_response)
            self.stats.record_outgoing(chat_id, ti, to, used_fs)
        except Exception as exc:
            logger.exception("response generation/sending failed: %s", exc)
            try:
                await message.reply_text("Сталася помилка. Спробуйте ще раз.")
            except Exception as notify_exc:
                logger.exception("failed to notify user: %s", notify_exc)

        max_history_length = self.config.get_file_paths_and_limits().get("max_history_length", 1000)
        if isinstance(max_history_length, int) and max_history_length >= 3:
            self.chat_history_manager.prune_history(chat_id, max_history_length)

    async def _process_message_content(self, message: MessageWrapper) -> Tuple[Optional[str], bool, bool]:
        paths_and_limits: Dict[str, Any] = self.config.get_file_paths_and_limits()
        audio_dir: Optional[str] = paths_and_limits.get("audio_folder_path")
        image_dir: Optional[str] = paths_and_limits.get("image_folder_path") or audio_dir
        files_dir: Optional[str] = paths_and_limits.get("files_folder_path") or audio_dir

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

        if getattr(message, "document", None) and inspect.iscoroutinefunction(getattr(message, "download_document", None)):
            if not files_dir:
                return None, False, False
            file_path: Optional[str] = None
            try:
                file_path = await message.download_document(files_dir)
                chat_id = message.chat_id
                self.openai_wrapper.upload_file_to_chat(chat_id, file_path)
                file_name = os.path.basename(file_path)
                return f"Файл додано: {file_name}. Тепер можу посилатись на нього у відповідях.", False, False
            finally:
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError as exc:
                        logger.exception("failed to remove temp doc file: %s", exc)

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

    @staticmethod
    def _sum_usage(obj) -> tuple[int, int]:
        def to_int(x):
            try:
                return int(x)
            except Exception:
                return 0

        cw = getattr(obj, "context_wrapper", None)
        u = getattr(cw, "usage", None) if cw else None
        if u:
            return to_int(getattr(u, "input_tokens", 0)), to_int(getattr(u, "output_tokens", 0))

        rr = getattr(obj, "raw_responses", None)
        if rr and hasattr(rr, "__iter__"):
            ti = sum(to_int(getattr(getattr(r, "usage", None), "input_tokens", 0)) for r in rr)
            to = sum(to_int(getattr(getattr(r, "usage", None), "output_tokens", 0)) for r in rr)
            return ti, to

        u = getattr(obj, "usage", None)
        if u:
            ti = to_int(getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", 0))
            to = to_int(getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", 0))
            return ti, to

        return 0, 0

    async def _generate_bot_response(self, chat_id: int) -> tuple[str, bool, int, int]:
        limit = self.config.get_file_paths_and_limits()["max_tokens"]
        maybe_coro = self.openai_wrapper.generate(
            model=self.config.get_openai_settings()["gpt_model"],
            messages=self.chat_history_manager.get_history(chat_id),
            max_tokens=limit,
            chat_id=chat_id,
        )
        response = await maybe_coro if inspect.isawaitable(maybe_coro) else maybe_coro
        ti, to = self._sum_usage(response)
        used_fs = bool(getattr(self.openai_wrapper, "used_file_search", lambda _: False)(response))
        text = self.openai_wrapper.extract_text(response)
        return text, used_fs, ti, to

    async def _send_response(
            self,
            message: MessageWrapper,
            bot_response: str,
            is_voice: bool,
            used_file_search: bool = False,
    ) -> None:
        if is_voice:
            if used_file_search:
                await message.reply_text("[search:on]")
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

        text_to_send = bot_response if not used_file_search else "[search:on]\n" + bot_response
        await message.reply_text(text_to_send)

