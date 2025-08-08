# voice_processor.py
from openai import OpenAI, AsyncOpenAI
from datetime import datetime
import os
import aiohttp


class VoiceProcessor:
    def __init__(self, api_key: str, whisper_model: str, tts_model: str):
        self.api_key = api_key
        self.whisper_model = whisper_model
        self.tts_model = tts_model

    async def transcribe_voice_message(self, voice_message_path):
        """Transcribe a voice message asynchronously using Whisper."""
        print("Voice file received")
        try:
            client = AsyncOpenAI(api_key=self.api_key)
            with open(voice_message_path, "rb") as audio_file:
                response = await client.audio.transcriptions.create(
                    model=self.whisper_model,
                    file=audio_file,
                )
            print(f"Voice message: {response.text}")
            return response.text
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

    async def voice_to_voice_chat(self, voice_message_path, model, voice, folder_path):
        """Send a voice message to the API asynchronously and return the response file path."""
        if not folder_path or not os.path.isdir(folder_path):
            print("Warning: Provided folder path is invalid. Using current directory.")
            folder_path = os.getcwd()

        async with aiohttp.ClientSession() as session:
            with open(voice_message_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("model", model)
                data.add_field("voice", voice)
                data.add_field(
                    "file",
                    f,
                    filename=os.path.basename(voice_message_path),
                    content_type="audio/ogg",
                )

                async with session.post(
                    "https://api.openai.com/v1/audio/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=data,
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        print(f"Error in voice chat: {resp.status} {text}")
                        return ""
                    content = await resp.read()

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        file_name = os.path.join(folder_path, f"response_{timestamp}.mp3")
        with open(file_name, "wb") as out_file:
            out_file.write(content)

        return file_name
