# test_chat_history_manager.py
import unittest
from chat_history_manager import ChatHistoryManager  # replace 'your_module' with the actual module name


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


if __name__ == "__main__":
    unittest.main()
