# message_handler.py
import os
import logging
from typing import Tuple, Optional, Dict, Any
from telegram import Update, Bot
from telegram.ext import CallbackContext
from src.aisus.message_wrapper import MessageWrapper
from src.aisus.config_parser import ConfigReader
from src.aisus.chat_history_manager import ChatHistoryManager
from src.aisus.openai_wrapper import OpenAIWrapper
import time
import inspect

logger: logging.Logger = logging.getLogger(__name__)


class CustomMessageHandler:
    def __init__(
        self,
        config: ConfigReader,
        chat_history_manager: ChatHistoryManager,
        openai_wrapper: OpenAIWrapper,
        chat_wrapper: Optional[OpenAIWrapper] = None,
        chat_model: Optional[str] = None,
    ) -> None:
        self.config: ConfigReader = config
        self.chat_history_manager: ChatHistoryManager = chat_history_manager
        self.openai_wrapper: OpenAIWrapper = openai_wrapper
        self.chat_wrapper: OpenAIWrapper = chat_wrapper or openai_wrapper
        self.chat_model: Optional[str] = chat_model or config.get_openai_settings().get("gpt_model")
        self.authenticated_users: Dict[int, bool] = {}
        self.started_at = time.monotonic()
        self.tokens_in = 0
        self.tokens_out = 0
        self.messages_in = 0
        self.messages_out = 0
        self.per_message_stats = []

    async def handle_message(self, update: Update, context: CallbackContext) -> None:
        msg = getattr(update, "message", None) or getattr(update, "effective_message", None)
        if not msg:
            return

        chat = getattr(update, "effective_chat", None) or getattr(getattr(msg, "chat", None), None)
        if not chat:
            return
        chat_id = chat.id

        bot_username = (await context.bot.get_me()).username
        raw_text = (getattr(msg, "text", None) or getattr(msg, "caption", None) or "")
        message_text_for_auth = raw_text.replace(f"@{bot_username}", "").strip()

        if not await self._should_process_message(context.bot, MessageWrapper(update)):
            return

        if not self.authenticated_users.get(chat_id):
            password = self.config.get_system_messages().get("password", "")
            if message_text_for_auth == password or password == "":
                self.authenticated_users[chat_id] = True
                await msg.reply_text(self.config.get_system_messages()["auth_success"])
            else:
                await msg.reply_text(self.config.get_system_messages()["auth_prompt"])
            return

        try:
            wrapped_message = MessageWrapper(update)
            user_message, is_voice, is_image = await self._process_message_content(wrapped_message)
            if not user_message:
                return

            self.messages_in += 1
            first_name = wrapped_message.from_user_first_name

            history = self.chat_history_manager.get_history(chat_id)
            if not history or history[0].get("role") != "system":
                self.chat_history_manager.add_system_message(
                    chat_id, self.config.get_system_messages().get("gpt_prompt", "")
                )

            self._update_chat_history(chat_id, first_name, user_message, is_voice, is_image)
            bot_response, used_fs, used_ws = await self._generate_bot_response(chat_id)
            await self._send_response(wrapped_message, bot_response, is_voice, used_fs, used_ws)
            self.chat_history_manager.add_bot_message(chat_id, bot_response)
            self.messages_out += 1

        except Exception as exc:
            logger.exception("response generation/sending failed: %s", exc)
            try:
                await msg.reply_text(self.config.get_system_messages()["error_message"])
            except Exception as notify_exc:
                logger.exception("failed to notify user: %s", notify_exc)

    @staticmethod
    async def _should_process_message(bot: Bot, message: MessageWrapper) -> bool:
        is_private = getattr(message, "chat_type", None) == "private"

        text = getattr(message, "text", "") or ""
        caption = getattr(message, "caption", "") or ""

        bot_username = (await bot.get_me()).username
        has_mention = (f"@{bot_username}" in text) or (f"@{bot_username}" in caption)

        is_reply_to_bot = bool(
            getattr(message, "reply_to_message", None)
            and getattr(message, "reply_to_message_from_user_username", None) == bot_username
        )

        return is_private or has_mention or is_reply_to_bot

    async def _handle_user_message(self, message: MessageWrapper) -> None:
        user_message, is_voice, is_image = await self._process_message_content(message)
        if not user_message:
            return

        self.messages_in += 1
        first_name = message.from_user_first_name
        chat_id = message.chat_id

        history = self.chat_history_manager.get_history(chat_id)
        if not history or history[0].get("role") != "system":
            self.chat_history_manager.add_system_message(
                chat_id, self.config.get_system_messages().get("gpt_prompt", "")
            )

        self._update_chat_history(chat_id, first_name, user_message, is_voice, is_image)

        try:
            bot_response, used_fs, used_ws = await self._generate_bot_response(chat_id)
            await self._send_response(message, bot_response, is_voice, used_fs, used_ws)
            self.chat_history_manager.add_bot_message(chat_id, bot_response)
            self.messages_out += 1
        except Exception as exc:
            logger.exception("response generation/sending failed: %s", exc)
            try:
                await message.reply_text(
                    self.config.get_system_messages()["error_message"]
                )
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
                transcribed_text: str = self.openai_wrapper.transcribe_voice_message(voice_message_path)
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
                return (
                    self.config.get_system_messages()[
                        "file_added_template"
                    ].format(file_name=file_name),
                    False,
                    False,
                )
            finally:
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError as exc:
                        logger.exception("failed to remove temp doc file: %s", exc)

        return message.text, False, False

    async def _analyze_image_with_openai(self, image_path: str) -> str:
        limit = self.config.get_file_paths_and_limits()["max_tokens"]
        return await self.openai_wrapper.analyze_image(
            image_path=image_path,
            prompt="What's in this image?",
            model="gpt-4o-mini",
            max_tokens=limit
        )

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

    async def _generate_bot_response(self, chat_id: int) -> tuple[str, bool, bool]:
        limit = self.config.get_file_paths_and_limits()["max_tokens"]
        model_name = self.chat_model or self.config.get_openai_settings()["gpt_model"]
        maybe_coro = self.chat_wrapper.generate(
            model=model_name,
            messages=self.chat_history_manager.get_history(chat_id),
            max_tokens=limit,
            chat_id=chat_id,
        )
        response = await maybe_coro if inspect.isawaitable(maybe_coro) else maybe_coro
        if response is None:
            raise RuntimeError("chat client returned no response")
        ti, to = self._sum_usage(response)
        used_fs = self.chat_wrapper.used_file_search(response)
        used_ws = self.chat_wrapper.used_web_search(response)
        self.tokens_in += ti
        self.tokens_out += to
        self.per_message_stats.append({
            "chat_id": chat_id,
            "tokens_in": ti,
            "tokens_out": to,
            "tokens_total": ti + to,
            "used_file_search": used_fs,
            "used_web_search": used_ws,
        })
        text = self.chat_wrapper.extract_text(response)
        if not text.strip():
            raise RuntimeError("chat client returned empty text")
        return text, used_fs, used_ws

    async def _send_response(
            self,
            message: MessageWrapper,
            bot_response: str,
            is_voice: bool,
            used_file_search: bool = False,
            used_web_search: bool = False,
    ) -> None:
        tags = []
        if used_file_search:
            tags.append("[filesearch:on]")
        if used_web_search:
            tags.append("[websearch:on]")
        tag_block = "\n".join(tags)
        if is_voice:
            if tag_block:
                await message.reply_text(tag_block)
            audio_dir_opt: Optional[str] = self.config.get_file_paths_and_limits().get("audio_folder_path")
            if audio_dir_opt:
                os.makedirs(audio_dir_opt, exist_ok=True)
            voice_response_file: str = self.openai_wrapper.generate_voice_response_and_save_file(
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
        text_to_send = f"{tag_block}\n{bot_response}" if tag_block else bot_response
        await message.reply_text(text_to_send)

    async def clear_history_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        chat_id: int = update.effective_chat.id
        self.chat_history_manager.clear_history(chat_id)
        await update.message.reply_text(
            self.config.get_system_messages()["history_cleared"]
        )

    async def resend_last_as_voice_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
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
            await update.message.reply_text(
                self.config.get_system_messages()["no_previous_message"]
            )
            return

        audio_dir_opt: Optional[str] = self.config.get_file_paths_and_limits().get("audio_folder_path")
        if audio_dir_opt:
            os.makedirs(audio_dir_opt, exist_ok=True)

        voice_file: str = self.openai_wrapper.generate_voice_response_and_save_file(
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
        total_messages = max(1, self.messages_out)
        avg_in = self.tokens_in // total_messages
        avg_out = self.tokens_out // total_messages
        file_search_uses = sum(1 for it in self.per_message_stats if it.get("used_file_search"))
        web_search_uses = sum(1 for it in self.per_message_stats if it.get("used_web_search"))
        return {
            "uptime_seconds": int(time.monotonic() - self.started_at),
            "messages_in": self.messages_in,
            "messages_out": self.messages_out,
            "total_tokens_in": self.tokens_in,
            "total_tokens_out": self.tokens_out,
            "avg_tokens_in_per_message": avg_in,
            "avg_tokens_out_per_message": avg_out,
            "file_search_uses": file_search_uses,
            "web_search_uses": web_search_uses,
        }

    async def stats_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        s = self.get_stats()
        secs = s["uptime_seconds"]
        h, m, sec = secs // 3600, (secs % 3600) // 60, secs % 60
        lines = [
            f"uptime: {h:02d}:{m:02d}:{sec:02d}",
            f"messages in: {s['messages_in']}",
            f"messages out: {s['messages_out']}",
            f"tokens in: {s['total_tokens_in']} (avg {s['avg_tokens_in_per_message']})",
            f"tokens out: {s['total_tokens_out']} (avg {s['avg_tokens_out_per_message']})",
            f"file search used: {s['file_search_uses']}",
            f"web search used: {s['web_search_uses']}",
        ]
        await update.message.reply_text("\n".join(lines))

    async def audio_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        text_to_speak = " ".join(getattr(context, "args", [])).strip()
        if not text_to_speak:
            await update.message.reply_text(
                self.config.get_system_messages()["no_text_to_speak"]
            )
            return

        audio_dir = self.config.get_file_paths_and_limits().get("audio_folder_path") or ""
        if audio_dir:
            os.makedirs(audio_dir, exist_ok=True)

        voice_file = self.openai_wrapper.generate_voice_response_and_save_file(
            text_to_speak,
            self.config.get_openai_settings().get("vocalizer_voice"),
            audio_dir,
        )
        await update.message.reply_voice(voice_file)
        if os.path.exists(voice_file):
            try:
                os.remove(voice_file)
            except OSError as exc:
                logger.exception("failed to remove temp tts file: %s", exc)

    async def show_files_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        chat_id = update.effective_chat.id
        vs_id = self.openai_wrapper.chat_vector_stores.get(chat_id)
        if not vs_id:
            await update.message.reply_text(
                self.config.get_system_messages()["no_files"]
            )
            return
        files = self.openai_wrapper.list_files_in_chat(chat_id)
        if not files:
            await update.message.reply_text(
                self.config.get_system_messages()["no_files"]
            )
            return
        lines = [f"{f['id']} - {f['filename']}" for f in files]
        header = self.config.get_system_messages()["files_header"]
        await update.message.reply_text(f"{header}\n" + "\n".join(lines))

    async def remove_file_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        chat_id = update.effective_chat.id
        if not context.args:
            await update.message.reply_text(
                self.config.get_system_messages()["file_id_required"]
            )
            return
        file_id = context.args[0].strip()
        ok = self.openai_wrapper.remove_file_from_chat(chat_id, file_id)
        if ok:
            await update.message.reply_text(
                self.config.get_system_messages()[
                    "file_deleted_template"
                ].format(file_id=file_id)
            )
        else:
            await update.message.reply_text(
                self.config.get_system_messages()[
                    "file_delete_failed_template"
                ].format(file_id=file_id)
            )

    async def clear_files_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        chat_id = update.effective_chat.id
        ok = self.openai_wrapper.clear_files_in_chat(chat_id)
        if ok:
            await update.message.reply_text(
                self.config.get_system_messages()["files_cleared"]
            )
        else:
            await update.message.reply_text(
                self.config.get_system_messages()["files_clear_failed"]
            )

    async def _is_command_for_me(self, update: Update, context: CallbackContext) -> bool:
        chat_type = update.effective_chat.type
        if chat_type in ("group", "supergroup"):
            text = (update.effective_message.text or "").strip()
            if not text.startswith("/"):
                return False
            bot_username = (await context.bot.get_me()).username
            first_token = text.split()[0]
            if f"@{bot_username}" not in first_token:
                return False

        chat_id = update.effective_chat.id
        if not self.authenticated_users.get(chat_id):
            password = self.config.get_system_messages().get("password", "")
            if password == "":
                self.authenticated_users[chat_id] = True
            else:
                await update.message.reply_text(
                    self.config.get_system_messages()["auth_prompt"]
                )
                return False

        return True