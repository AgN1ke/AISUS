import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from message_handler import MessageHandler
from config_reader import ConfigReader
from chat_history_manager import ChatHistoryManager
from pyrogram.types import Message, User
from message_wrapper import MessageWrapper


class TestMessageHandler(unittest.TestCase):
    def setUp(self):
        # Mock dependencies
        self.client = MagicMock()
        self.voice_processor = MagicMock()
        self.openai_wrapper = MagicMock()

        # Mocking client.get_me() to return a mock username
        self.client.get_me = AsyncMock(return_value=MagicMock(username='mock_bot'))

        # Use real ConfigReader and ChatHistoryManager
        self.config = ConfigReader('test_config.ini')
        self.chat_history_manager = ChatHistoryManager()

        self.voice_processor.transcribe_voice_message = MagicMock(return_value="some text")
        # mock_response = AsyncMock()
        # mock_response.choices = [AsyncMock(message=AsyncMock(content="Mocked bot response"))]
        # self.openai_wrapper.chat_completion.return_value = mock_response

        # Create an instance of MessageHandler
        self.message_handler = MessageHandler(
            self.config,
            self.client,
            self.voice_processor,
            self.chat_history_manager,
            self.openai_wrapper
        )

    @patch('message_handler.MessageWrapper')  # Mock MessageWrapper
    def test_handle_message_internal(self, mock_message_wrapper):
        # Create a mock message
        mock_message = MagicMock(spec=Message)
        mock_message.chat.id = 123
        mock_message.text = "Hello"
        mock_user = MagicMock(spec=User)
        mock_user.first_name = "John"
        mock_user.last_name = "Doe"
        mock_message.from_user = mock_user

        # Wrapping the mock message
        wrapped_message = MessageWrapper(mock_message)
        mock_message_wrapper.return_value = wrapped_message

        # Call the method under test
        self.message_handler.handle_message_internal(self.client, wrapped_message)

        # Assertions to check if the correct methods were called with expected arguments
        self.chat_history_manager.add_user_message.assert_called_with(123, "Hello")
        self.openai_wrapper.chat_completion.assert_called()
        # Add more assertions based on the expected behavior of handle_message_internal


if __name__ == '__main__':
    unittest.main()
