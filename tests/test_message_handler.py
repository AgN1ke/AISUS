# test_message_handler.py
import unittest
from unittest.mock import Mock
from src.message_handler import MessageHandler
from src.config_reader import ConfigReader
from src.chat_history_manager import ChatHistoryManager


class TestMessageHandler(unittest.TestCase):

    def setUp(self):
        self.config = ConfigReader("../configs/test_config.ini")
        self.chat_history_manager = ChatHistoryManager()
        self.client = Mock()
        self.voice_processor = Mock()
        self.openai_wrapper = Mock()
        self.message_handler = MessageHandler(
            config=self.config,
            client=self.client,
            voice_processor=self.voice_processor,
            chat_history_manager=self.chat_history_manager,
            openai_wrapper=self.openai_wrapper
        )

    def test_should_process_message(self):
        # Setup
        message = Mock()
        message.voice = None
        message.text = "Hello"
        message.chat_id = 123
        message.reply_to_message = None
        message.from_user_first_name = "Test User"

        # Execution and Verification
        self.assertTrue(self.message_handler._should_process_message(self.client, message))

    def test_mock_text_dialog(self):
        # Setup
        message = Mock()
        message.voice = None
        message.text = "Hello"
        message.chat_id = 123
        message.reply_to_message = None
        message.from_user_first_name = "Test User"

        predefined_response = "Hi there!"
        self.openai_wrapper.chat_completion.return_value = Mock(
            choices=[Mock(message=Mock(content=predefined_response))])

        # Execution
        self.message_handler._handle_message(self.client, message)

        # Verification
        self.assertEqual(len(self.chat_history_manager.get_history(message.chat_id)), 3)
        self.assertIn(predefined_response, self.chat_history_manager.get_history(message.chat_id)[-1]['content'])


if __name__ == '__main__':
    unittest.main()
