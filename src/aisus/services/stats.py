import time
from typing import Dict, Any, List


class StatsService:
    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self.tokens_in = 0
        self.tokens_out = 0
        self.messages_in = 0
        self.messages_out = 0
        self.per_message_stats: List[Dict[str, Any]] = []

    def record_incoming(self) -> None:
        self.messages_in += 1

    def record_outgoing(self, chat_id: int, tokens_in: int, tokens_out: int, used_fs: bool) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.messages_out += 1
        self.per_message_stats.append({
            "chat_id": chat_id,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
            "used_file_search": used_fs,
        })

    def get_stats(self) -> Dict[str, Any]:
        total_messages = max(1, self.messages_out)
        avg_in = self.tokens_in // total_messages
        avg_out = self.tokens_out // total_messages
        file_search_uses = sum(1 for it in self.per_message_stats if it.get("used_file_search"))
        return {
            "uptime_seconds": int(time.monotonic() - self.started_at),
            "messages_in": self.messages_in,
            "messages_out": self.messages_out,
            "total_tokens_in": self.tokens_in,
            "total_tokens_out": self.tokens_out,
            "avg_tokens_in_per_message": avg_in,
            "avg_tokens_out_per_message": avg_out,
            "file_search_uses": file_search_uses,
        }
