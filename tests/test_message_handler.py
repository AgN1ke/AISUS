# tests/test_message_handler.py
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

from src.message_handler import CustomMessageHandler
from src.chat_history_manager import ChatHistoryManager
from src.heroku_config_parser import ConfigReader


class TestMessageHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.config: ConfigReader = ConfigReader()
        self.history: ChatHistoryManager = ChatHistoryManager()
        self.bot: Mock = Mock()
        self.bot.get_me = AsyncMock(return_value=SimpleNamespace(username="testbot"))
        self.voice: Mock = Mock()
        self.openai: Mock = Mock()
        self.handler: CustomMessageHandler = CustomMessageHandler(
            config=self.config,
            voice_processor=self.voice,
            chat_history_manager=self.history,
            openai_wrapper=self.openai,
        )

    def test_should_process_message(self) -> None:
        msg: Mock = Mock()
        msg.chat_type = "private"
        msg.text = "Hello"
        msg.reply_to_message = None
        coro = self.handler._should_process_message(self.bot, msg)
        self.assertTrue(asyncio.run(coro))

    def test_mock_text_dialog(self) -> None:
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

        self.openai.chat_completion.return_value = Mock(
            choices=[Mock(message=Mock(content="Hi there!"))]
        )

        self.handler.authenticated_users[123] = True
        asyncio.run(self.handler._handle_user_message(msg))

        history = self.history.get_history(msg.chat_id)
        self.assertEqual(len(history), 3)
        self.assertIn("Hi there!", history[-1]["content"])
