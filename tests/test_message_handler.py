# tests/test_message_handler.py
import asyncio
import os
import unittest
import tempfile
import shutil
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import Mock, AsyncMock, patch

from telegram import Update
from telegram.ext import CallbackContext

from src.aisus.chat_history_manager import ChatHistoryManager
from src.aisus.config_parser import ConfigReader
from src.aisus.message_handler import CustomMessageHandler


class TestMessageHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root: str = tempfile.mkdtemp(prefix="aisus-tests-")
        self.audio_dir: str = os.path.join(self.tmp_root, "audio")
        self.image_dir: str = os.path.join(self.tmp_root, "images")
        self.files_dir: str = os.path.join(self.tmp_root, "files")
        self.env_patch: Any = patch.dict(os.environ, {
            "SYSTEM_MESSAGES_GPT_PROMPT": "Welcome",
            "SYSTEM_MESSAGES_VOICE_MESSAGE_AFFIX": "Voice:",
            "SYSTEM_MESSAGES_IMAGE_MESSAGE_AFFIX": "You sent an image.",
            "SYSTEM_MESSAGES_IMAGE_CAPTION_AFFIX": "Caption:",
            "SYSTEM_MESSAGES_IMAGE_SENCE_AFFIX": "Scene:",
            "PASSWORD": "",
            "FILE_PATHS_AUDIO_FOLDER": self.audio_dir,
            "FILE_PATHS_IMAGE_FOLDER": self.image_dir,
            "FILE_PATHS_FILES_FOLDER": self.files_dir,
        }, clear=False)
        self.env_patch.start()
        self.config: ConfigReader = ConfigReader()
        self.history: ChatHistoryManager = ChatHistoryManager()
        self.bot: Mock = Mock()
        self.bot.get_me = AsyncMock(return_value=SimpleNamespace(username="testbot"))
        self.openai: Mock = Mock()
        self.handler: CustomMessageHandler = CustomMessageHandler(
            config=self.config,
            chat_history_manager=self.history,
            openai_wrapper=self.openai
        )

    def tearDown(self) -> None:
        self.env_patch.stop()
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_should_process_message(self) -> None:
        msg: Mock = Mock()
        msg.chat_type = "private"
        msg.text = "Hello"
        msg.caption = None
        msg.reply_to_message = None
        coro = self.handler._should_process_message(self.bot, msg)
        self.assertTrue(asyncio.run(coro))

    def test_mock_text_dialog_uses_generate(self) -> None:
        msg: Mock = Mock()
        msg.voice = None
        msg.photo = None
        msg.text = "Hello"
        msg.chat_id = 123
        msg.message = Mock(caption=None)
        msg.from_user_first_name = "Test User"
        msg.from_user_last_name = None
        msg.reply_text = AsyncMock()
        msg.reply_voice = AsyncMock()

        self.openai.generate.return_value = Mock()
        self.openai.extract_text.return_value = "Hi there!"

        self.handler.authenticated_users[123] = True
        asyncio.run(self.handler._handle_user_message(msg))

        self.openai.generate.assert_called()
        _, kwargs = self.openai.generate.call_args
        assert kwargs.get("chat_id") == 123

        history = self.history.get_history(msg.chat_id)
        self.assertEqual(3, len(history))
        self.assertIn("Hi there!", history[-1]["content"])

    def test_voice_download_path_and_cleanup(self) -> None:
        created_path: Optional[str] = None

        async def download_voice(download_dir: str) -> str:
            nonlocal created_path
            os.makedirs(download_dir, exist_ok=True)
            created_path = os.path.join(download_dir, "dummy_voice.ogg")
            with open(created_path, "wb") as f:
                f.write(b"ogg")
            return created_path

        self.openai.transcribe_voice_message = Mock(return_value="ok")

        msg: Mock = Mock()
        msg.voice = True
        msg.photo = None
        msg.text = None
        msg.download_voice = AsyncMock(side_effect=download_voice)
        msg.message = Mock(caption=None)

        result_text, is_voice, is_image = asyncio.run(self.handler._process_message_content(msg))

        self.assertEqual(result_text, "ok")
        self.assertTrue(is_voice)
        self.assertFalse(is_image)
        self.assertIsNotNone(created_path)
        self.assertTrue(created_path.startswith(self.audio_dir))
        self.assertFalse(os.path.exists(created_path))

    def test_image_download_path_and_cleanup(self) -> None:
        created_path: Optional[str] = None

        async def download_image(download_dir: str) -> str:
            nonlocal created_path
            os.makedirs(download_dir, exist_ok=True)
            created_path = os.path.join(download_dir, "dummy_image.jpg")
            with open(created_path, "wb") as f:
                f.write(b"\xff\xd8\xff")
            return created_path

        self.handler._analyze_image_with_openai = AsyncMock(return_value="a cat")

        msg: Mock = Mock()
        msg.voice = None
        msg.photo = [object()]
        msg.text = None
        msg.download_image = AsyncMock(side_effect=download_image)
        msg.message = SimpleNamespace(caption="cap")

        result_text, is_voice, is_image = asyncio.run(self.handler._process_message_content(msg))

        self.assertIsInstance(result_text, str)
        self.assertFalse(is_voice)
        self.assertTrue(is_image)
        self.assertIsNotNone(created_path)
        self.assertTrue(created_path.startswith(self.image_dir))
        self.assertFalse(os.path.exists(created_path))

    def test_document_upload_and_cleanup(self) -> None:
        created_path: Optional[str] = None

        async def download_document(download_dir: str) -> str:
            nonlocal created_path
            os.makedirs(download_dir, exist_ok=True)
            created_path = os.path.join(download_dir, "doc.txt")
            with open(created_path, "wb") as f:
                f.write(b"hello")
            return created_path

        self.openai.upload_file_to_chat = Mock(return_value=("file_1", "vs_1"))

        msg: Mock = Mock()
        msg.voice = None
        msg.photo = None
        msg.text = None
        msg.document = True
        msg.chat_id = 777
        msg.download_document = AsyncMock(side_effect=download_document)
        msg.message = SimpleNamespace(caption=None)

        result_text, is_voice, is_image = asyncio.run(self.handler._process_message_content(msg))

        self.assertIn("Файл додано:", result_text)
        self.openai.upload_file_to_chat.assert_called_once_with(777, created_path)
        self.assertFalse(os.path.exists(created_path))
        self.assertFalse(is_voice)
        self.assertFalse(is_image)

    def test_tts_response_cleanup(self) -> None:
        os.makedirs(self.audio_dir, exist_ok=True)
        tts_path: str = os.path.join(self.audio_dir, "tts.ogg")
        with open(tts_path, "wb") as f:
            f.write(b"ogg")
        self.openai.generate_voice_response_and_save_file = Mock(return_value=tts_path)

        msg: Mock = Mock()
        msg.reply_voice = AsyncMock()
        msg.reply_text = AsyncMock()

        asyncio.run(self.handler._send_response(msg, "hello", is_voice=True))

        msg.reply_voice.assert_awaited_once_with(tts_path)
        self.assertFalse(os.path.exists(tts_path))

    def test_tts_creates_audio_dir(self) -> None:
        import shutil
        if os.path.isdir(self.audio_dir):
            shutil.rmtree(self.audio_dir)

        async def reply_voice(*args, **kwargs):
            return None

        def generate_voice_response_and_save_file(text: str, voice: Optional[str], audio_dir: str) -> str:
            self.assertTrue(os.path.isdir(audio_dir))
            os.makedirs(audio_dir, exist_ok=True)
            tts_path: str = os.path.join(audio_dir, "tts_created.ogg")
            with open(tts_path, "wb") as f:
                f.write(b"ogg")
            return tts_path

        self.openai.generate_voice_response_and_save_file = Mock(side_effect=generate_voice_response_and_save_file)

        msg: Mock = Mock()
        msg.reply_voice = AsyncMock(side_effect=reply_voice)
        msg.reply_text = AsyncMock()

        asyncio.run(self.handler._send_response(msg, "hello", is_voice=True))

        self.assertTrue(os.path.isdir(self.audio_dir))

    def test_image_dir_falls_back_to_audio_dir(self) -> None:
        created_path: Optional[str] = None

        async def download_image(download_dir: str) -> str:
            nonlocal created_path
            os.makedirs(download_dir, exist_ok=True)
            created_path = os.path.join(download_dir, "fallback.jpg")
            with open(created_path, "wb") as f:
                f.write(b"\xff\xd8\xff")
            return created_path

        with patch.dict(os.environ, {"FILE_PATHS_IMAGE_FOLDER": ""}, clear=False):
            cfg_fallback: ConfigReader = ConfigReader()
            handler_fallback: CustomMessageHandler = CustomMessageHandler(
                config=cfg_fallback,
                chat_history_manager=self.history,
                openai_wrapper=self.openai
            )

        handler_fallback._analyze_image_with_openai = AsyncMock(return_value="ok")

        msg: Mock = Mock()
        msg.voice = None
        msg.photo = [object()]
        msg.text = None
        msg.download_image = AsyncMock(side_effect=download_image)
        msg.message = SimpleNamespace(caption=None)

        result_text, is_voice, is_image = asyncio.run(handler_fallback._process_message_content(msg))

        self.assertIsInstance(result_text, str)
        self.assertFalse(is_voice)
        self.assertTrue(is_image)
        self.assertIsNotNone(created_path)
        self.assertTrue(created_path.startswith(self.audio_dir))
        self.assertFalse(os.path.exists(created_path))

    def test_tts_cleanup_oserror_logged(self) -> None:
        tts_path: str = os.path.join(self.audio_dir, "tts.ogg")
        os.makedirs(self.audio_dir, exist_ok=True)
        with open(tts_path, "wb") as f:
            f.write(b"ogg")

        self.openai.generate_voice_response_and_save_file = Mock(return_value=tts_path)

        msg: Mock = Mock()
        msg.reply_voice = AsyncMock()
        msg.reply_text = AsyncMock()

        with patch("src.aisus.message_handler.os.remove", side_effect=OSError("boom")), \
                self.assertLogs("src.aisus.message_handler", level="ERROR") as captured:
            asyncio.run(self.handler._send_response(msg, "hello", is_voice=True))

        msg.reply_voice.assert_awaited_once_with(tts_path)
        self.assertTrue(any("failed to remove temp tts file" in rec for rec in captured.output))

    def test_auth_with_text_mention_in_group(self) -> None:
        with patch.dict(os.environ, {"PASSWORD": "secret"}, clear=False):
            cfg: ConfigReader = ConfigReader()
            handler: CustomMessageHandler = CustomMessageHandler(cfg, self.history, self.openai)

        update = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=1001)
        update.message = Mock()
        update.message.text = "@testbot secret"
        update.message.caption = None
        update.message.chat = SimpleNamespace(type="group")
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()

        context = Mock(spec=CallbackContext)
        context.bot = self.bot

        asyncio.run(handler.handle_message(update, context))

        self.assertTrue(handler.authenticated_users.get(1001))
        update.message.reply_text.assert_awaited()

    def test_auth_with_text_reply_in_group(self) -> None:
        with patch.dict(os.environ, {"PASSWORD": "secret"}, clear=False):
            cfg: ConfigReader = ConfigReader()
            handler: CustomMessageHandler = CustomMessageHandler(cfg, self.history, self.openai)
        update = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=1002)
        update.message = Mock()
        update.message.text = "secret"
        update.message.caption = None
        update.message.chat = SimpleNamespace(type="group")
        update.message.reply_to_message = SimpleNamespace(from_user=SimpleNamespace(username="testbot"))
        update.message.reply_text = AsyncMock()

        context = Mock(spec=CallbackContext)
        context.bot = self.bot
        asyncio.run(handler.handle_message(update, context))
        self.assertTrue(handler.authenticated_users.get(1002))
        update.message.reply_text.assert_awaited()

    def test_auth_with_image_caption_mention_in_group(self) -> None:
        with patch.dict(os.environ, {"PASSWORD": "secret"}, clear=False):
            cfg: ConfigReader = ConfigReader()
            handler: CustomMessageHandler = CustomMessageHandler(cfg, self.history, self.openai)
        update = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=1003)
        update.message = Mock()
        update.message.text = None
        update.message.caption = "@testbot secret"
        update.message.chat = SimpleNamespace(type="group")
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()
        update.message.photo = [object()]

        context = Mock(spec=CallbackContext)
        context.bot = self.bot
        asyncio.run(handler.handle_message(update, context))
        self.assertTrue(handler.authenticated_users.get(1003))
        update.message.reply_text.assert_awaited()

    def test_auth_with_image_caption_reply_in_group(self) -> None:
        with patch.dict(os.environ, {"PASSWORD": "secret"}, clear=False):
            cfg: ConfigReader = ConfigReader()
            handler: CustomMessageHandler = CustomMessageHandler(cfg, self.history, self.openai)
        update = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=1004)
        update.message = Mock()
        update.message.text = None
        update.message.caption = "secret"
        update.message.chat = SimpleNamespace(type="group")
        update.message.reply_to_message = SimpleNamespace(from_user=SimpleNamespace(username="testbot"))
        update.message.reply_text = AsyncMock()
        update.message.photo = [object()]

        context = Mock(spec=CallbackContext)
        context.bot = self.bot
        asyncio.run(handler.handle_message(update, context))
        self.assertTrue(handler.authenticated_users.get(1004))
        update.message.reply_text.assert_awaited()

    def test_resend_last_as_voice_command_sends_last_bot_message_as_voice(self) -> None:
        chat_id: int = 555
        last_text: str = "Previous bot reply"
        self.history.add_bot_message(chat_id, last_text)

        os.makedirs(self.audio_dir, exist_ok=True)
        tts_path: str = os.path.join(self.audio_dir, "last.ogg")

        def generate(text: str, voice: Optional[str], audio_dir: str) -> str:
            with open(tts_path, "wb") as f:
                f.write(b"ogg")
            return tts_path

        self.openai.generate_voice_response_and_save_file = Mock(side_effect=generate)

        update: Mock = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=chat_id, type="private")
        update.message = Mock()
        update.message.reply_voice = AsyncMock()
        update.message.reply_text = AsyncMock()

        context: Mock = Mock(spec=CallbackContext)

        asyncio.run(self.handler.resend_last_as_voice_command(update, context))

        update.message.reply_voice.assert_awaited_once_with(tts_path)
        self.assertFalse(os.path.exists(tts_path))

    def test_audio_command_with_text(self) -> None:
        os.makedirs(self.audio_dir, exist_ok=True)
        tts_path = os.path.join(self.audio_dir, "audio.ogg")

        def gen(text: str, voice: Optional[str], audio_dir: str) -> str:
            with open(tts_path, "wb") as f:
                f.write(b"ogg")
            return tts_path

        self.openai.generate_voice_response_and_save_file = Mock(side_effect=gen)

        update = Mock()
        update.effective_chat = SimpleNamespace(id=123, type="private")
        update.message = Mock()
        update.message.reply_voice = AsyncMock()
        update.message.reply_text = AsyncMock()

        context = Mock(spec=CallbackContext)
        context.args = ["Test", "1", "2", "3"]

        asyncio.run(self.handler.audio_command(update, context))

        update.message.reply_voice.assert_awaited_once_with(tts_path)
        self.assertFalse(os.path.exists(tts_path))

    def test_audio_command_without_text(self) -> None:
        update = Mock()
        update.message = Mock()
        update.message.reply_voice = AsyncMock()
        update.message.reply_text = AsyncMock()

        context = Mock(spec=CallbackContext)
        context.args = []

        asyncio.run(self.handler.audio_command(update, context))

        update.message.reply_text.assert_awaited_once()
        update.message.reply_voice.assert_not_awaited()

    def test_showfiles_no_store(self) -> None:
        update = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=42, type="private")
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        self.openai.chat_vector_stores = {}

        context = Mock(spec=CallbackContext)

        asyncio.run(self.handler.show_files_command(update, context))

        update.message.reply_text.assert_awaited_once()

    def test_showfiles_with_files(self) -> None:
        update = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=43, type="private")
        update.message = Mock()
        update.message.reply_text = AsyncMock()

        self.openai.chat_vector_stores = {43: "vs_43"}
        self.openai.list_files_in_chat = Mock(return_value=[
            {"id": "f1", "filename": "a.txt"},
            {"id": "f2", "filename": "b.pdf"},
        ])

        context = Mock(spec=CallbackContext)
        asyncio.run(self.handler.show_files_command(update, context))

        self.openai.list_files_in_chat.assert_called_once_with(43)
        args, kwargs = update.message.reply_text.await_args
        self.assertIn("a.txt", args[0])
        self.assertIn("b.pdf", args[0])

    def test_removefile_success_and_arg_required(self) -> None:
        update = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=44, type="private")
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = Mock(spec=CallbackContext)

        context.args = []
        asyncio.run(self.handler.remove_file_command(update, context))
        update.message.reply_text.assert_awaited()
        update.message.reply_text.reset_mock()

        context.args = ["f123"]
        self.openai.remove_file_from_chat = Mock(return_value=True)
        asyncio.run(self.handler.remove_file_command(update, context))
        self.openai.remove_file_from_chat.assert_called_once_with(44, "f123")
        args, kwargs = update.message.reply_text.await_args
        self.assertIn("видалено", args[0])

    def test_clearfiles_success(self) -> None:
        update = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=45, type="private")
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = Mock(spec=CallbackContext)

        self.openai.clear_files_in_chat = Mock(return_value=True)
        asyncio.run(self.handler.clear_files_command(update, context))

        self.openai.clear_files_in_chat.assert_called_once_with(45)
        args, kwargs = update.message.reply_text.await_args
        self.assertIn("очищено", args[0])

    def test_group_document_without_mention_is_ignored(self) -> None:
        update = Mock(spec=Update)
        update.effective_chat = SimpleNamespace(id=2001)
        update.message = Mock()
        update.message.text = None
        update.message.caption = None
        update.message.chat = SimpleNamespace(type="group")
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()
        update.message.photo = None
        update.message.document = True

        context = Mock(spec=CallbackContext)
        context.bot = self.bot

        self.openai.generate = Mock()

        asyncio.run(self.handler.handle_message(update, context))

        self.openai.generate.assert_not_called()
        update.message.reply_text.assert_not_awaited()

    def test_send_response_adds_tags(self) -> None:
        msg: Mock = Mock()
        msg.reply_text = AsyncMock()
        msg.reply_voice = AsyncMock()

        asyncio.run(self.handler._send_response(msg, "hello", is_voice=False,
                                                used_file_search=True, used_web_search=False))
        msg.reply_text.assert_awaited()
        args, kwargs = msg.reply_text.await_args
        self.assertIn("[filesearch:on]", args[0])
        msg.reply_text.reset_mock()

        asyncio.run(self.handler._send_response(msg, "hello", is_voice=False,
                                                used_file_search=False, used_web_search=True))
        msg.reply_text.assert_awaited()
        args, kwargs = msg.reply_text.await_args
        self.assertIn("[websearch:on]", args[0])
        msg.reply_text.reset_mock()

        asyncio.run(self.handler._send_response(msg, "hello", is_voice=False,
                                                used_file_search=True, used_web_search=True))
        msg.reply_text.assert_awaited()
        args, kwargs = msg.reply_text.await_args
        self.assertIn("[filesearch:on]", args[0])
        self.assertIn("[websearch:on]", args[0])