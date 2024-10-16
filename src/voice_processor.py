# src/voice_processor.py

import base64

class VoiceProcessor:
    def __init__(self):
        pass  # Необхідні параметри перенесено до OpenAIRealtimeClient

    def encode_audio_to_base64(self, audio_file_path):
        """Кодує аудіофайл у формат Base64."""
        with open(audio_file_path, "rb") as audio_file:
            audio_bytes = audio_file.read()
            encoded_audio = base64.b64encode(audio_bytes).decode('utf-8')
        return encoded_audio
