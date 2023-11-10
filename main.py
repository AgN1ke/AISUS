import openai
import configparser
from pyrogram import Client, filters
from pyrogram.types import Message
from openai import OpenAI
import os
from datetime import datetime

# Создание экземпляра парсера и чтение конфигурационного файла
config = configparser.ConfigParser()
config.read('config.ini', encoding='utf-8')

# Read the welcome message
welcome_message = config['system_messages']['welcome_message']
# If you used a line delimiter, replace it with newline characters
welcome_message = welcome_message.replace(' | ', '\n')

# Получение значения ключа API для OpenAI
openai_api_key = config['openai']['api_key']

# Установка ключа API
openai.api_key = openai_api_key

# Получение настроек API для другого сервиса
api_id = config['myapi']['api_id']
api_hash = config['myapi']['api_hash']
session_name = config['myapi']['session_name']

# Инициализация клиента с полученными настройками
app = Client(session_name, api_id=api_id, api_hash=api_hash)
# Initialize chat histories dictionary
chat_histories = {}


# Функция для транскрибирования голосовых сообщений
async def transcribe_voice_message(voice_message_path):
    try:
        # Создаем отдельный клиент для OpenAI
        openai_client = OpenAI(api_key=openai_api_key)

        with open(voice_message_path, "rb") as audio_file:
            transcript_response = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        # Доступ к тексту из ответа
        return transcript_response.text
    except Exception as e:
        print(f"Ошибка при транскрипции: {e}")
        return ""


# Функция для генерации голосового ответа и сохранения в файл
async def generate_voice_response_and_save_file(text, voice="alloy",
                                                folder_path="C:\\Python_projects\\Smartest\\Audio"):
    openai_client = OpenAI(api_key=openai_api_key)
    response = openai_client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text
    )
    # Генерация уникального имени файла
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"{folder_path}\\response_{timestamp}.mp3"

    # Сохранение аудиофайла
    with open(file_name, "wb") as audio_file:
        audio_file.write(response.read())

    return file_name


@app.on_message(filters.private | (filters.group & (filters.reply | filters.mentioned)))
async def echo(client: Client, message: Message):
    # Get bot's username
    bot_username = (await client.get_me()).username

    # If the message is a reply but not a direct mention of the bot and not a reply to the bot's message, skip it
    if message.reply_to_message:
        if message.reply_to_message.from_user.username != bot_username and \
                (message.text is None or f"@{bot_username}" not in message.text):
            return


    if message.voice:
        print("Received a voice message...")
        voice_message_path = await message.download()
        transcribed_text = await transcribe_voice_message(voice_message_path)
        print(f"Transcribed text: {transcribed_text}")
        if transcribed_text:
            gpt_input = "Ты сейчас надиктовываешь текст для голосового сообщения: " + transcribed_text
        else:
            return  # Если не удалось транскрибировать голос, то не отвечаем
    else:
        gpt_input = message.text

    if gpt_input:
        # Update chat history
        chat_id = message.chat.id
        if chat_id not in chat_histories:
            chat_histories[chat_id] = [{"role": "system", "content": welcome_message}]

        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        chat_histories[chat_id].append({"role": "user", "content": f"{first_name} сказал: {gpt_input}"})
        print(f"{first_name} {last_name} ({chat_id}): {gpt_input}")

        # Generate response from GPT-4
        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4",
            messages=chat_histories[chat_id],
            max_tokens=4000
        )
        bot_response = response.choices[0].message.content
        chat_histories[chat_id].append({"role": "assistant", "content": bot_response})
        print(f"GPT prompt: {gpt_input}")
        print(f"Bot: {bot_response}")

        # Remove old messages from the history if their amount exceeds 4000 tokens
        while sum([len(m['content']) for m in chat_histories[chat_id] if m['role'] != 'system']) > 4000:
            for i in range(len(chat_histories[chat_id]) - 1, -1, -1):  # We start from the end of the list
                if chat_histories[chat_id][i]['role'] != 'system':
                    del chat_histories[chat_id][i]
                    break

        # Send response
        if message.voice:
            voice_response_file = await generate_voice_response_and_save_file(bot_response)
            await message.reply_voice(voice_response_file)

            if os.path.exists(voice_response_file):
                os.remove(voice_response_file)
        else:
            await message.reply_text(bot_response)


app.run()
