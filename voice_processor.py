import openai
from datetime import datetime


async def transcribe_voice_message(voice_message_path, whisper_model):
    """Transcribe a voice message using the Whisper model."""
    try:
        with open(voice_message_path, "rb") as audio_file:
            transcript_response = openai.Audio.transcriptions.create(
                model=whisper_model,
                file=audio_file
            )
        return transcript_response.text
    except Exception as e:
        print(f"Error in transcription: {e}")
        return ""


async def generate_voice_response_and_save_file(text, voice, folder_path, tts_model):
    """Generate a voice response and save it to a file."""
    response = openai.Audio.speech.create(
        model=tts_model,
        voice=voice,
        input=text
    )
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"{folder_path}/response_{timestamp}.mp3"
    with open(file_name, "wb") as audio_file:
        audio_file.write(response.read())
    return file_name
