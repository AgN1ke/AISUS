# test_chat_history_manager.py
import unittest

from src.aisus.chat_history_manager import ChatHistoryManager


class TestChatHistoryManager(unittest.TestCase):

    def setUp(self):
        self.manager = ChatHistoryManager()

    def test_add_message(self):
        chat_id = "test_chat_1"
        self.manager.add_user_message(chat_id, "dude1", "Hello, World!")
        history = self.manager.get_history(chat_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['content'], "dude1: Hello, World!")

    def test_calculate_history_length(self):
        chat_id = "test_chat_2"
        self.manager.add_user_message(chat_id, "dude2", "Hello")
        self.manager.add_bot_message(chat_id, "World")
        total_length = self.manager.calculate_history_length(chat_id)
        self.assertEqual(total_length, len("dude2: Hello") + len("World"))

    def test_prune_history(self):
        chat_id = "test_chat_3"
        for i in range(10):
            self.manager.add_user_message(chat_id, "dude3", f"Message {i}")

        self.manager.prune_history(chat_id, 25)  # Assuming each message is around 10 characters
        history = self.manager.get_history(chat_id)
        total_length = sum(len(m['content']) for m in history)
        self.assertTrue(total_length <= 25)
        self.assertLessEqual(len(history), 3)  # Exact number depends on message lengths

    def test_system_messages_not_pruned(self):
        chat_id = "test_chat_4"
        self.manager.add_system_message(chat_id, "System message")
        for i in range(5):
            self.manager.add_user_message(chat_id, "dude4", f"Message {i}")

        self.manager.prune_history(chat_id, 20)
        history = self.manager.get_history(chat_id)
        self.assertIn("System message", [m['content'] for m in history])

    def test_add_system_message(self):
        chat_id = "test_chat_5"
        self.manager.add_system_message(chat_id, "System init")
        history = self.manager.get_history(chat_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['content'], "System init")

        # Add another message and then another system message
        self.manager.add_user_message(chat_id, "dude5", "User message")
        self.manager.add_system_message(chat_id, "System update")
        history = self.manager.get_history(chat_id)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]['content'], "System update")

        # Add a system message identical to the first one
        self.manager.add_system_message(chat_id, "System update")
        history = self.manager.get_history(chat_id)
        # Length should not increase as the message is identical to the first one
        self.assertEqual(len(history), 3)

    def test_add_or_update_voice_message(self):
        chat_id = "test_chat_6"
        voice_message_affix = "Voice message 1"

        # Test adding a voice message
        self.manager.add_system_voice_affix_if_not_exist(chat_id, voice_message_affix)
        history = self.manager.get_history(chat_id)
        self.assertIn(voice_message_affix, [m['content'] for m in history])

        # Test updating the voice message
        self.manager.add_system_voice_affix_if_not_exist(chat_id, voice_message_affix)
        history = self.manager.get_history(chat_id)
        self.assertIn(voice_message_affix, [m['content'] for m in history])

        # Test removing the voice message
        self.manager.remove_system_voice_affix_if_exist(chat_id, voice_message_affix)
        history = self.manager.get_history(chat_id)
        self.assertNotIn(voice_message_affix, [m['content'] for m in history])

    def test_prune_with_system_and_voice_messages(self):
        chat_id = "test_chat_7"
        voice_message_affix = "Voice message"

        # Add system and voice messages
        self.manager.add_system_message(chat_id, "System init")
        self.manager.add_system_voice_affix_if_not_exist(chat_id, voice_message_affix)

        # Add a series of user and assistant messages
        for i in range(10):
            self.manager.add_user_message(chat_id, "dude7", f"User message {i}")
            self.manager.add_bot_message(chat_id, f"Assistant response {i}")

        # Prune the history
        self.manager.prune_history(chat_id, 100)  # Assuming each message is around 20 characters

        history = self.manager.get_history(chat_id)
        system_messages = [m for m in history if m['role'] == 'system']
        voice_messages = [m for m in history if m['content'] == voice_message_affix]

        # Check that system and voice messages are still present
        self.assertGreater(len(system_messages), 0, "System messages should not be pruned")
        self.assertGreater(len(voice_messages), 0, "Voice messages should not be pruned")

        # Check that the total length is within the limit
        total_length = sum(len(m['content']) for m in history)
        self.assertTrue(total_length <= 100)

    def test_add_system_voice_affix_position(self):
        chat_id = "test_chat_8"
        voice_message_affix = "Voice message affix"

        self.manager.add_system_message(chat_id, "System update")

        # Test insertion at position 0 in an empty chat history
        self.manager.add_user_message(chat_id, "dude8", "First message")
        self.manager.add_system_voice_affix_if_not_exist(chat_id, voice_message_affix)
        history_0 = self.manager.get_history(chat_id)
        self.assertEqual(len(history_0), 3)
        self.assertEqual(history_0[1]['content'], voice_message_affix)

        # Test insertion at position 1 in a chat history with one non-system message
        self.manager.add_user_message(chat_id, "dude8", "Second message")
        self.manager.add_system_voice_affix_if_not_exist(chat_id, voice_message_affix)
        history_1 = self.manager.get_history(chat_id)
        self.assertEqual(len(history_1), 4)
        self.assertEqual(history_1[1]['content'], voice_message_affix)


if __name__ == "__main__":
    unittest.main()
