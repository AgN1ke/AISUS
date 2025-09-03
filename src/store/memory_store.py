from typing import Dict, List
from src.domain.models import ChatMessage


class ChatHistoryManager:
    """In-memory implementation of chat history storage."""

    def __init__(self) -> None:
        self.chat_histories: Dict[int, List[ChatMessage]] = {}

    def _add_message(self, chat_id: int, role: str, content: str) -> None:
        if chat_id not in self.chat_histories:
            self.chat_histories[chat_id] = []
        self.chat_histories[chat_id].append(ChatMessage(role, content))

    def clear_history(self, chat_id: int) -> None:
        self.chat_histories.pop(chat_id, None)

    def add_user_message(self, chat_id: int, name: str, content: str) -> None:
        self._add_message(chat_id, "user", f"{name}: {content}")

    def add_bot_message(self, chat_id: int, content: str) -> None:
        self._add_message(chat_id, "assistant", content)

    def get_history(self, chat_id: int) -> List[ChatMessage]:
        return self.chat_histories.get(chat_id, [])

    def calculate_history_length(self, chat_id: int) -> int:
        return sum(len(m.content) for m in self.chat_histories.get(chat_id, []))

    def prune_history(self, chat_id: int, max_length: int = 124000) -> None:
        history = self.chat_histories.get(chat_id)
        if not history:
            return
        while self.calculate_history_length(chat_id) > max_length:
            for i, message in enumerate(history):
                if message.role != "system":
                    history.pop(i)
                    break

    def add_system_message(self, chat_id: int, content: str) -> None:
        history = self.chat_histories.get(chat_id)
        if history is None:
            self.chat_histories[chat_id] = [ChatMessage("system", content)]
        elif not history or history[0].content != content:
            history.insert(0, ChatMessage("system", content))

    def add_system_voice_affix_if_not_exist(self, chat_id: int, voice_message_affix: str) -> None:
        history = self.chat_histories.get(chat_id)
        if not history:
            self.chat_histories[chat_id] = [ChatMessage("system", voice_message_affix)]
            return
        exists = any(m.role == "system" and m.content == voice_message_affix for m in history)
        if not exists:
            pos = 1 if len(history) > 1 else 0
            history.insert(pos, ChatMessage("system", voice_message_affix))

    def remove_system_voice_affix_if_exist(self, chat_id: int, voice_message_affix: str) -> None:
        history = self.chat_histories.get(chat_id)
        if not history:
            return
        self.chat_histories[chat_id] = [m for m in history if not (m.role == "system" and m.content == voice_message_affix)]
