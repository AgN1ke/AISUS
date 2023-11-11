# voice_processor.py
from openai import OpenAI
from datetime import datetime
import os


class VoiceProcessor:
    def __init__(self, api_key: str, whisper_model: str, tts_model: str):
        self.api_key = api_key
        self.whisper_model = whisper_model
        self.tts_model = tts_model

    def transcribe_voice_message(self, voice_message_path):
        """Transcribe a voice message using the Whisper model."""
        try:
            with open(voice_message_path, "rb") as audio_file:
                client = OpenAI(api_key=self.api_key)
                transcript_response = client.audio.transcriptions.create(
                    model=self.whisper_model,
                    file=audio_file
                )
            return transcript_response.text
        except Exception as e:
            print(f"Error in transcription: {e}")
            return ""

    def generate_voice_response_and_save_file(self, text, voice, folder_path):
        """Generate a voice response and save it to a file."""
        # Validate or update folder_path
        if not folder_path or not os.path.isdir(folder_path):
            print("Warning: Provided folder path is invalid. Using current directory.")
            folder_path = os.getcwd()

        client = OpenAI(api_key=self.api_key)
        response = client.audio.speech.create(
            model=self.tts_model,
            voice=voice,
            input=text
        )

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        file_name = os.path.join(folder_path, f"response_{timestamp}.mp3")

        with open(file_name, "wb") as audio_file:
            audio_file.write(response.read())

        return file_name
