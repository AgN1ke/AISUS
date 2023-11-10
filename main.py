from pyrogram import Client, filters
from pyrogram.types import Message
import openai
import os
from utilities import read_config, format_message
from voice_processor import transcribe_voice_message, generate_voice_response_and_save_file
from chat_history_manager import ChatHistoryManager


# Read and parse the configuration
config = read_config('config.ini')

# Format system messages
welcome_message = format_message(config['system_messages']['welcome_message'])
voice_message_afix = format_message(config['system_messages']['voice_message_afix'])

# OpenAI API settings
openai.api_key = config['openai']['api_key']
gpt_model = config['openai']['gpt_model']
whisper_model = config['openai']['whisper_model']
tts_model = config['openai']['tts_model']
vocalizer_voice = config['openai']['vocalizer_voice']

# Other API settings
api_id = config['myapi']['api_id']
api_hash = config['myapi']['api_hash']
session_name = config['myapi']['session_name']

# File paths and limits
audio_folder_path = config['file_paths']['audio_folder']
max_tokens = int(config['limits']['max_tokens'])

# Initialize the Pyrogram client
app = Client(session_name, api_id=api_id, api_hash=api_hash)

# Initialize chat histories
chat_history_manager = ChatHistoryManager()


@app.on_message(filters.private | (filters.group & (filters.reply | filters.mentioned)))
async def handle_message(client: Client, message: Message):
    """Handle incoming messages and generate responses."""
    chat_id = message.chat.id
    bot_username = (await client.get_me()).username
    if message.reply_to_message and message.reply_to_message.from_user.username != bot_username \
            and (message.text is None or f"@{bot_username}" not in message.text):
        return
    chat_history_manager.add_system_message(chat_id, welcome_message)
    if message.voice:
        voice_message_path = await message.download()
        transcribed_text = await transcribe_voice_message(voice_message_path, whisper_model)
        if not transcribed_text:
            return
        gpt_input = transcribed_text
        chat_history_manager.add_or_update_voice_message(chat_id, voice_message_afix, transcribed_text)
    else:
        gpt_input = message.text
        chat_history_manager.add_or_update_voice_message(chat_id, voice_message_afix, None)

    if gpt_input:
        first_name = message.from_user.first_name
        chat_history_manager.add_message(chat_id, 'user', f"{first_name} said: {gpt_input}")
        response = openai.ChatCompletion.create(
            model=gpt_model,
            messages=chat_history_manager.get_history(chat_id),
            max_tokens=max_tokens
        )
        bot_response = response.choices[0].message.content
        chat_history_manager.prune_history(chat_id, max_tokens)

        if message.voice:
            voice_response_file = await generate_voice_response_and_save_file(
                bot_response, vocalizer_voice, audio_folder_path, tts_model)
            await message.reply_voice(voice_response_file)
            if os.path.exists(voice_response_file):
                os.remove(voice_response_file)
        else:
            await message.reply_text(bot_response)


if __name__ == "__main__":
    app.run()
