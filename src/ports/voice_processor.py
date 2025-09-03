from typing import Optional, Protocol


class VoiceProcessorPort(Protocol):
    """Port for speech-to-text and text-to-speech operations."""

    def transcribe_voice_message(self, voice_message_path: str) -> str: ...

    def generate_voice_response_and_save_file(self, text: str, voice: Optional[str], folder_path: str) -> str: ...
