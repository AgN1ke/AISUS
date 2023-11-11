# chat_history_manager.py
class ChatHistoryManager:
    def __init__(self):
        self.chat_histories = {}

    def _add_message(self, chat_id, role, content):
        if chat_id not in self.chat_histories:
            self.chat_histories[chat_id] = []
        self.chat_histories[chat_id].append({"role": role, "content": content})

    def add_user_message(self, chat_id, name, content):
        self._add_message(chat_id, 'user', f"{name}: {content}")

    def add_bot_message(self, chat_id, content):
        self._add_message(chat_id, 'assistant', content)

    def get_history(self, chat_id):
        return self.chat_histories.get(chat_id, [])

    def calculate_history_length(self, chat_id):
        total_length = 0
        if chat_id in self.chat_histories:
            for message in self.chat_histories[chat_id]:
                total_length += len(message['content'])
        return total_length

    def prune_history(self, chat_id, max_length):
        if chat_id in self.chat_histories:
            while self.calculate_history_length(chat_id) > max_length:
                # Remove the oldest non-system message
                for i in range(len(self.chat_histories[chat_id])):
                    if self.chat_histories[chat_id][i]['role'] != 'system':
                        self.chat_histories[chat_id].pop(i)
                        break  # Break after removing one message, then recheck the total length

    def add_system_message(self, chat_id, content):
        if chat_id not in self.chat_histories:
            self.chat_histories[chat_id] = [{"role": "system", "content": content}]
        elif self.chat_histories[chat_id][0]["content"] != content:
            self.chat_histories[chat_id].insert(0, {"role": "system", "content": content})

    def add_or_update_voice_message(self, chat_id, voice_message_afix, transcribed_text):
        if transcribed_text:
            if not any(item["content"] == voice_message_afix for item in self.chat_histories[chat_id]):
                self.chat_histories[chat_id].insert(1, {"role": "system", "content": voice_message_afix})
        else:
            self.chat_histories[chat_id] = \
                [item for item in self.chat_histories[chat_id] if item["content"] != voice_message_afix]
