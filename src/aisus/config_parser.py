# config_parser.py
from typing import Any, Dict, Optional
from dotenv import load_dotenv
import os

load_dotenv()


def _format_message(message: Optional[str]) -> str:
    return "" if message is None else message.replace(" | ", "\n")


class ConfigReader:
    def __init__(self) -> None:
        self.gpt_prompt: str = _format_message(os.getenv("SYSTEM_MESSAGES_GPT_PROMPT"))
        self.voice_message_affix: str = _format_message(os.getenv("SYSTEM_MESSAGES_VOICE_MESSAGE_AFFIX"))
        self.image_message_affix: str = _format_message(
            os.getenv("SYSTEM_MESSAGES_IMAGE_MESSAGE_AFFIX", "Ти отримав зображення."))
        self.image_caption_affix: str = _format_message(
            os.getenv("SYSTEM_MESSAGES_IMAGE_CAPTION_AFFIX", "Під ним такий підпис відправника:"))
        self.image_sence_affix: str = _format_message(
            os.getenv("SYSTEM_MESSAGES_IMAGE_SENCE_AFFIX", "На картинці зображено:"))
        self.password: str = _format_message(os.getenv("PASSWORD"))

        self.api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
        self.gpt_model: Optional[str] = os.getenv("OPENAI_GPT_MODEL")
        self.api_mode: str = os.getenv("OPENAI_API_MODE", "responses")
        self.reasoning_effort: Optional[str] = os.getenv("OPENAI_REASONING_EFFORT")
        self.whisper_model: Optional[str] = os.getenv("OPENAI_WHISPER_MODEL")
        self.tts_model: Optional[str] = os.getenv("OPENAI_TTS_MODEL")
        self.vocalizer_voice: Optional[str] = os.getenv("OPENAI_VOCALIZER_VOICE")
        self.search_enabled: bool = os.getenv("OPENAI_SEARCH_ENABLED", "true").strip().lower() in {"1", "true", "yes",
                                                                                                   "on"}
        self.web_search_enabled: bool = os.getenv("OPENAI_WEB_SEARCH_ENABLED", "true").strip().lower() in {"1", "true",
                                                                                                           "yes", "on"}

        self.bot_token: Optional[str] = os.getenv("MYAPI_BOT_TOKEN")

        self.audio_folder_path: Optional[str] = os.getenv("FILE_PATHS_AUDIO_FOLDER")
        self.image_folder_path: Optional[str] = os.getenv("FILE_PATHS_IMAGE_FOLDER")
        self.files_folder_path: Optional[str] = os.getenv("FILE_PATHS_FILES_FOLDER")

        self.max_tokens: int = int(os.getenv("LIMITS_MAX_TOKENS", "3000"))
        self.max_history_length: int = int(os.getenv("LIMITS_MAX_HISTORY_LENGTH", "124000"))

    def get_system_messages(self) -> Dict[str, str]:
        return {
            "gpt_prompt": self.gpt_prompt,
            "voice_message_affix": self.voice_message_affix,
            "image_message_affix": self.image_message_affix,
            "image_caption_affix": self.image_caption_affix,
            "image_sence_affix": self.image_sence_affix,
            "password": self.password,
        }

    def get_openai_settings(self) -> Dict[str, Optional[str]]:
        return {
            "api_key": self.api_key,
            "gpt_model": self.gpt_model,
            "whisper_model": self.whisper_model,
            "tts_model": self.tts_model,
            "vocalizer_voice": self.vocalizer_voice,
            "api_mode": self.api_mode,
            "reasoning_effort": self.reasoning_effort,
            "search_enabled": self.search_enabled,
            "web_search_enabled": self.web_search_enabled,
        }

    def get_api_settings(self) -> Dict[str, Optional[str]]:
        return {
            "bot_token": self.bot_token,
        }

    def get_file_paths_and_limits(self) -> Dict[str, Any]:
        return {
            "audio_folder_path": self.audio_folder_path,
            "image_folder_path": self.image_folder_path,
            "files_folder_path": self.files_folder_path,
            "max_tokens": self.max_tokens,
            "max_history_length": self.max_history_length,
        }
