# chat_history_manager.py
class ChatHistoryManager:
    def __init__(self):
        self.chat_histories = {}

    def add_message(self, chat_id, role, content):
        if chat_id not in self.chat_histories:
            self.chat_histories[chat_id] = []
        self.chat_histories[chat_id].append({"role": role, "content": content})

    def add_user_message(self, chat_id, content):
        self.add_message(chat_id, 'user', content)

    def add_bot_message(self, chat_id, content):
        self.add_message(chat_id, 'assistant', content)

    def get_history(self, chat_id):
        return self.chat_histories.get(chat_id, [])

    def prune_history(self, chat_id, max_length):
        if chat_id in self.chat_histories:
            while sum([len(m['content']) for m in self.chat_histories[chat_id] if m['role'] != 'system']) > max_length:
                for i in range(len(self.chat_histories[chat_id]) - 1, -1, -1):
                    if self.chat_histories[chat_id][i]['role'] != 'system':
                        del self.chat_histories[chat_id][i]
                        break

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
