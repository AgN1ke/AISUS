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
            "SYSTEM_MESSAGES_IMAGE_MESSAGE_AFFIX": "Img:",
            "SYSTEM_MESSAGES_IMAGE_CAPTION_AFFIX": "Cap:",
            "SYSTEM_MESSAGES_IMAGE_SENCE_AFFIX": "Scene:",
            "SYSTEM_MESSAGES_AUTH_SUCCESS": "Auth ok",
            "SYSTEM_MESSAGES_AUTH_PROMPT": "Enter pass",
            "SYSTEM_MESSAGES_ERROR": "Oops",
            "SYSTEM_MESSAGES_FILE_ADDED_TEMPLATE": "Added {file_name}",
            "SYSTEM_MESSAGES_HISTORY_CLEARED": "Cleared",
            "SYSTEM_MESSAGES_NO_PREVIOUS_MESSAGE": "No prev",
            "SYSTEM_MESSAGES_NO_TEXT_TO_SPEAK": "No text",
            "SYSTEM_MESSAGES_NO_FILES": "No files",
            "SYSTEM_MESSAGES_FILES_HEADER": "Files:",
            "SYSTEM_MESSAGES_FILE_ID_REQUIRED": "Need id",
            "SYSTEM_MESSAGES_FILE_DELETED_TEMPLATE": "Del {file_id}",
            "SYSTEM_MESSAGES_FILE_DELETE_FAILED_TEMPLATE": "No del {file_id}",
            "SYSTEM_MESSAGES_FILES_CLEARED": "All clear",
            "SYSTEM_MESSAGES_FILES_CLEAR_FAILED": "No clear",
            "PASSWORD": "pw",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_GPT_MODEL": "gpt-x",
            "OPENAI_API_MODE": "responses",
            "OPENAI_REASONING_EFFORT": "medium",
            "OPENAI_SEARCH_ENABLED": "false",
            "OPENAI_BASE_URL": "https://api.deepseek.com",
            "MYAPI_BOT_TOKEN": "token",
            "FILE_PATHS_AUDIO_FOLDER": "/tmp/a",
            "FILE_PATHS_IMAGE_FOLDER": "/tmp/i",
            "FILE_PATHS_FILES_FOLDER": "/tmp/f",
            "LIMITS_MAX_TOKENS": "4096",
            "LIMITS_MAX_HISTORY_LENGTH": "200000",
        }, clear=False)
        env_patch.start()
        cfg: ConfigReader = ConfigReader()

        sys_msgs = cfg.get_system_messages()
        self.assertEqual(sys_msgs["gpt_prompt"], "Hello")
        self.assertEqual(sys_msgs["voice_message_affix"], "Voice:")
        self.assertEqual(sys_msgs["image_message_affix"], "Img:")
        self.assertEqual(sys_msgs["image_caption_affix"], "Cap:")
        self.assertEqual(sys_msgs["image_sence_affix"], "Scene:")
        self.assertEqual(sys_msgs["auth_success"], "Auth ok")
        self.assertEqual(sys_msgs["auth_prompt"], "Enter pass")
        self.assertEqual(sys_msgs["error_message"], "Oops")
        self.assertEqual(sys_msgs["file_added_template"], "Added {file_name}")
        self.assertEqual(sys_msgs["history_cleared"], "Cleared")
        self.assertEqual(sys_msgs["no_previous_message"], "No prev")
        self.assertEqual(sys_msgs["no_text_to_speak"], "No text")
        self.assertEqual(sys_msgs["no_files"], "No files")
        self.assertEqual(sys_msgs["files_header"], "Files:")
        self.assertEqual(sys_msgs["file_id_required"], "Need id")
        self.assertEqual(sys_msgs["file_deleted_template"], "Del {file_id}")
        self.assertEqual(sys_msgs["file_delete_failed_template"], "No del {file_id}")
        self.assertEqual(sys_msgs["files_cleared"], "All clear")
        self.assertEqual(sys_msgs["files_clear_failed"], "No clear")
        self.assertEqual(sys_msgs["password"], "pw")

        openai_settings = cfg.get_openai_settings()
        self.assertEqual(openai_settings["api_key"], "sk-test")
        self.assertEqual(openai_settings["gpt_model"], "gpt-x")
        self.assertEqual(openai_settings["api_mode"], "responses")
        self.assertEqual(openai_settings["reasoning_effort"], "medium")
        self.assertFalse(openai_settings["search_enabled"])
        self.assertEqual(openai_settings["base_url"], "https://api.deepseek.com")

        api_settings = cfg.get_api_settings()
        self.assertEqual(api_settings["bot_token"], "token")

        paths = cfg.get_file_paths_and_limits()
        self.assertEqual(paths["audio_folder_path"], "/tmp/a")
        self.assertEqual(paths["image_folder_path"], "/tmp/i")
        self.assertEqual(paths["files_folder_path"], "/tmp/f")
        self.assertEqual(paths["max_tokens"], 4096)
        self.assertEqual(paths["max_history_length"], 200000)
        env_patch.stop()

    def test_defaults_when_missing(self) -> None:
        env_patch: Any = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        cfg: ConfigReader = ConfigReader()

        sys_msgs = cfg.get_system_messages()
        self.assertEqual(sys_msgs["image_message_affix"], "Ти отримав зображення.")
        self.assertEqual(sys_msgs["image_caption_affix"], "Під ним такий підпис відправника:")
        self.assertEqual(sys_msgs["image_sence_affix"], "На картинці зображено:")
        self.assertEqual(sys_msgs["no_files"], "Немає завантажених файлів у цьому чаті.")

        openai_settings = cfg.get_openai_settings()
        self.assertEqual(openai_settings["api_mode"], "responses")
        self.assertIsNone(openai_settings["reasoning_effort"])
        self.assertTrue(openai_settings["search_enabled"])
        self.assertIsNone(openai_settings["base_url"])

        paths = cfg.get_file_paths_and_limits()
        self.assertIsNone(paths["image_folder_path"])
        self.assertIsNone(paths["files_folder_path"])
        self.assertEqual(paths["max_tokens"], 3000)
        self.assertEqual(paths["max_history_length"], 124000)
        env_patch.stop()

    def test_search_enabled_true(self) -> None:
        env_patch: Any = patch.dict(os.environ, {
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_GPT_MODEL": "gpt-x",
            "OPENAI_SEARCH_ENABLED": "true",
        }, clear=False)
        env_patch.start()
        cfg: ConfigReader = ConfigReader()
        openai_settings = cfg.get_openai_settings()
        self.assertTrue(openai_settings["search_enabled"])
        env_patch.stop()

    def test_search_enabled_false(self) -> None:
        env_patch: Any = patch.dict(os.environ, {
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_GPT_MODEL": "gpt-x",
            "OPENAI_SEARCH_ENABLED": "false",
        }, clear=False)
        env_patch.start()
        cfg: ConfigReader = ConfigReader()
        openai_settings = cfg.get_openai_settings()
        self.assertFalse(openai_settings["search_enabled"])
        env_patch.stop()
