import unittest
from unittest.mock import AsyncMock, Mock
import os
from src.message_handler import CustomMessageHandler
from src.chat_history_manager import ChatHistoryManager
from src.heroku_config_parser import ConfigReader


class TestCustomMessageHandler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ['OPENAI_API_KEY'] = 'key'
        os.environ['OPENAI_GPT_MODEL'] = 'gpt-4o'
        os.environ['OPENAI_WHISPER_MODEL'] = 'whisper'
        os.environ['OPENAI_TTS_MODEL'] = 'tts-1'
        os.environ['OPENAI_VOCALIZER_VOICE'] = 'nova'
        os.environ['SYSTEM_MESSAGES_WELCOME_MESSAGE'] = 'hi'
        os.environ['SYSTEM_MESSAGES_VOICE_MESSAGE_AFFIX'] = 'voice'
        os.environ['PASSWORD'] = ''
        os.environ['SYSTEM_MESSAGES_IMAGE_MESSAGE_AFFIX'] = 'img'
        os.environ['SYSTEM_MESSAGES_IMAGE_CAPTION_AFFIX'] = 'cap'
        os.environ['SYSTEM_MESSAGES_IMAGE_SENCE_AFFIX'] = 'sence'
        self.config = ConfigReader()
        self.voice_processor = Mock()
        self.chat_history_manager = ChatHistoryManager()
        self.openai_wrapper = Mock()
        self.handler = CustomMessageHandler(self.config, self.voice_processor,
                                            self.chat_history_manager, self.openai_wrapper)

    async def test_should_process_message(self):
        bot = AsyncMock()
        bot.get_me = AsyncMock(return_value=Mock(username='bot'))
        message = Mock()
        message.chat_type = 'private'
        message.text = 'hello'
        message.reply_to_message = None
        message.reply_to_message_from_user_username = None
        result = await self.handler._should_process_message(bot, message)
        self.assertTrue(result)

