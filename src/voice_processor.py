# voice_processor.py
import base64
import os
from pydub import AudioSegment

class VoiceProcessor:
    def __init__(self):
        pass  # Немає необхідності у параметрах ініціалізації для цього класу

    def encode_audio_to_base64(self, audio_file_path):
        """Кодує аудіофайл у формат Base64 та приводить його до формату PCM 16-bit, 24kHz, 1 канал."""
        try:
            audio = AudioSegment.from_file(audio_file_path)
            # Перетворюємо аудіо до потрібного формату
            audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
            raw_data = audio.raw_data
            encoded_audio = base64.b64encode(raw_data).decode('utf-8')
            return encoded_audio
        except Exception as e:
            print(f"Помилка при кодуванні аудіо: {e}")
            return None

    def save_audio_from_base64(self, audio_base64, output_path):
        """Зберігає аудіо з Base64 у файл."""
        try:
            audio_bytes = base64.b64decode(audio_base64)
            with open(output_path, 'wb') as f:
                f.write(audio_bytes)
        except Exception as e:
            print(f"Помилка при збереженні аудіо: {e}")
