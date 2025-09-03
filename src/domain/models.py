from dataclasses import dataclass


@dataclass
class ChatMessage:
    """Represents a single chat message."""
    role: str
    content: str
