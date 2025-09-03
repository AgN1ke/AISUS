import logging
import os
from typing import Optional
from telegram import Update
from telegram.ext import CallbackContext
from src.aisus.chat_history_manager import ChatHistoryManager
from src.aisus.config_parser import ConfigReader
from src.aisus.voice_processor import VoiceProcessor
from src.aisus.openai_wrapper import OpenAIWrapper
from src.aisus.services.auth import AuthService
from src.aisus.services.stats import StatsService

logger = logging.getLogger(__name__)


class CommandHandler:
    def __init__(
        self,
        config: ConfigReader,
        voice_processor: VoiceProcessor,
        chat_history_manager: ChatHistoryManager,
        openai_wrapper: OpenAIWrapper,
        auth_service: AuthService,
        stats_service: StatsService,
    ) -> None:
        self.config = config
        self.voice_processor = voice_processor
        self.chat_history_manager = chat_history_manager
        self.openai_wrapper = openai_wrapper
        self.auth = auth_service
        self.stats = stats_service

    async def clear_history_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        chat_id = update.effective_chat.id
        self.chat_history_manager.clear_history(chat_id)
        await update.message.reply_text("Історію чау очищено.")

    async def resend_last_as_voice_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        chat_id = update.effective_chat.id
        history = self.chat_history_manager.get_history(chat_id)
        last_bot_text: Optional[str] = None
        for entry in reversed(history):
            role = str(entry.get("role", ""))
            content = entry.get("content", "")
            if role == "assistant" and isinstance(content, str) and content.strip():
                last_bot_text = content
                break
        if not last_bot_text:
            await update.message.reply_text("Немає попереднього повідомлення бота для цього чату.")
            return
        audio_dir_opt: Optional[str] = self.config.get_file_paths_and_limits().get("audio_folder_path")
        if audio_dir_opt:
            os.makedirs(audio_dir_opt, exist_ok=True)
        voice_file = self.voice_processor.generate_voice_response_and_save_file(
            last_bot_text,
            self.config.get_openai_settings()["vocalizer_voice"],
            audio_dir_opt or "",
        )
        await update.message.reply_voice(voice_file)
        if os.path.exists(voice_file):
            try:
                os.remove(voice_file)
            except OSError as exc:
                logger.exception("failed to remove temp tts file: %s", exc)

    async def stats_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        s = self.stats.get_stats()
        secs = s["uptime_seconds"]
        h, m, sec = secs // 3600, (secs % 3600) // 60, secs % 60
        lines = [
            f"uptime: {h:02d}:{m:02d}:{sec:02d}",
            f"messages in: {s['messages_in']}",
            f"messages out: {s['messages_out']}",
            f"tokens in: {s['total_tokens_in']} (avg {s['avg_tokens_in_per_message']})",
            f"tokens out: {s['total_tokens_out']} (avg {s['avg_tokens_out_per_message']})",
            f"file search used: {sum(1 for it in self.stats.per_message_stats if it.get('used_file_search'))}",
        ]
        await update.message.reply_text("\n".join(lines))

    async def audio_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        text_to_speak = " ".join(getattr(context, "args", [])).strip()
        if not text_to_speak:
            await update.message.reply_text("Немає тексту для озвучення.")
            return
        audio_dir = self.config.get_file_paths_and_limits().get("audio_folder_path") or ""
        if audio_dir:
            os.makedirs(audio_dir, exist_ok=True)
        voice_file = self.voice_processor.generate_voice_response_and_save_file(
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
            await update.message.reply_text("Немає завантажених файлів у цьому чаті.")
            return
        files = self.openai_wrapper.list_files_in_chat(chat_id)
        if not files:
            await update.message.reply_text("Немає завантажених файлів у цьому чаті.")
            return
        lines = [f"{f['id']} – {f['filename']}" for f in files]
        await update.message.reply_text("Файли:\n" + "\n".join(lines))

    async def remove_file_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        chat_id = update.effective_chat.id
        if not context.args:
            await update.message.reply_text("Вкажіть file_id після команди.")
            return
        file_id = context.args[0].strip()
        ok = self.openai_wrapper.remove_file_from_chat(chat_id, file_id)
        if ok:
            await update.message.reply_text(f"Файл {file_id} видалено.")
        else:
            await update.message.reply_text(f"Не вдалося видалити файли {file_id}.")

    async def clear_files_command(self, update: Update, context: CallbackContext) -> None:
        if not await self._is_command_for_me(update, context):
            return
        chat_id = update.effective_chat.id
        ok = self.openai_wrapper.clear_files_in_chat(chat_id)
        if ok:
            await update.message.reply_text("Усі файли очищено для цього чату.")
        else:
            await update.message.reply_text("Не вдалося очистити файли.")

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
        return await self.auth.ensure_auth_for_command(update)
