# tests/test_config_parser.py
import os
import unittest
from typing import Any
from unittest.mock import patch
from src.aisus.config_parser import ConfigReader


class TestConfigParser(unittest.TestCase):
    def test_reads_from_env(self) -> None:
        env_patch: Any = patch.dict(os.environ, {
            "SYSTEM_MESSAGES_GPT_PROMPT": "Hello",
            "SYSTEM_MESSAGES_VOICE_MESSAGE_AFFIX": "Voice:",
            "PASSWORD": "pw",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_GPT_MODEL": "gpt-x",
            "MYAPI_BOT_TOKEN": "token",
            "FILE_PATHS_AUDIO_FOLDER": "/tmp/a",
            "FILE_PATHS_IMAGE_FOLDER": "/tmp/i",
            "LIMITS_MAX_TOKENS": "4096",
            "LIMITS_MAX_HISTORY_LENGTH": "200000",
        }, clear=False)
        env_patch.start()
        cfg: ConfigReader = ConfigReader()
        self.assertEqual(cfg.get_system_messages()["gpt_prompt"], "Hello")
        self.assertEqual(cfg.get_system_messages()["voice_message_affix"], "Voice:")
        self.assertEqual(cfg.get_system_messages()["password"], "pw")
        self.assertEqual(cfg.get_openai_settings()["api_key"], "sk-test")
        self.assertEqual(cfg.get_openai_settings()["gpt_model"], "gpt-x")
        self.assertEqual(cfg.get_api_settings()["bot_token"], "token")
        self.assertEqual(cfg.get_file_paths_and_limits()["audio_folder_path"], "/tmp/a")
        self.assertEqual(cfg.get_file_paths_and_limits()["image_folder_path"], "/tmp/i")
        self.assertEqual(cfg.get_file_paths_and_limits()["max_tokens"], 4096)
        self.assertEqual(cfg.get_file_paths_and_limits()["max_history_length"], 200000)
        env_patch.stop()

    def test_defaults_when_missing(self) -> None:
        env_patch: Any = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        cfg: ConfigReader = ConfigReader()
        self.assertEqual(cfg.get_system_messages()["image_message_affix"], "Ти отримав зображення.")
        self.assertEqual(cfg.get_system_messages()["image_caption_affix"], "Під ним такий підпис відправника:")
        self.assertEqual(cfg.get_system_messages()["image_sence_affix"], "На картинці зображено:")
        self.assertIsNone(cfg.get_file_paths_and_limits()["image_folder_path"])
        self.assertEqual(cfg.get_file_paths_and_limits()["max_tokens"], 3000)
        self.assertEqual(cfg.get_file_paths_and_limits()["max_history_length"], 124000)
        env_patch.stop()
