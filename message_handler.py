# message_handler.py
from pyrogram.types import Message
from message_wrapper import MessageWrapper
from config_reader import ConfigReader
from pyrogram import Client, filters
from voice_processor import VoiceProcessor
from chat_history_manager import ChatHistoryManager
from openai_wrapper import OpenAIWrapper
import os


class MessageHandler:
    def __init__(self,
                 config: ConfigReader,
                 client: Client,
                 voice_processor: VoiceProcessor,
                 chat_history_manager: ChatHistoryManager,
                 openai_wrapper: OpenAIWrapper):

        self.config = config
        self.client = client
        self.voice_processor = voice_processor
        self.chat_history_manager = chat_history_manager
        message_filters = filters.private | (filters.group & (filters.reply | filters.mentioned))
        self.client.on_message(message_filters)(self.handle_message)
        self.openai_wrapper = openai_wrapper

    async def handle_message(self, client, message: Message):
        """Handle incoming messages and generate responses asynchronously."""
        chat_id = message.chat.id
        bot_username = (await client.get_me()).username
        if message.reply_to_message and message.reply_to_message.from_user.username != bot_username \
                and (message.text is None or f"@{bot_username}" not in message.text):
            return
        self.chat_history_manager.add_system_message(chat_id, self.config.get_system_messages()['welcome_message'])
        if message.voice:
            voice_message_path = await message.download()
            transcribed_text = await self.voice_processor.transcribe_voice_message(voice_message_path)
            if not transcribed_text:
                return
            user_message = transcribed_text
            self.chat_history_manager.add_or_update_voice_message(
                chat_id, self.config.get_system_messages()['voice_message_afix'], transcribed_text)
        else:
            user_message = message.text
            self.chat_history_manager.add_or_update_voice_message(
                chat_id, self.config.get_system_messages()['voice_message_afix'], None)

        if user_message:
            first_name = message.from_user.first_name
            last_name = message.from_user.last_name
            self.chat_history_manager.add_user_message(chat_id, user_message)
            print(f"{first_name} {last_name} ({chat_id}): {user_message}")

            response = self.openai_wrapper.chat_completion(
                model=self.config.get_openai_settings()['gpt_model'],
                messages=self.chat_history_manager.get_history(chat_id),
                max_tokens=self.config.get_file_paths_and_limits()['max_tokens'])
            bot_response = response.choices[0].message.content
            self.chat_history_manager.add_bot_message(chat_id, bot_response)
            print(f"AISUS: {bot_response}")

            self.chat_history_manager.prune_history(chat_id, self.config.get_openai_settings()['max_tokens'])

            if message.voice:
                voice_response_file = await self.voice_processor.generate_voice_response_and_save_file(
                    bot_response,
                    self.config.get_openai_settings()['vocalizer_voice'],
                    self.config.get_file_paths_and_limits()['audio_folder_path'])
                await message.reply_voice(voice_response_file)
                if os.path.exists(voice_response_file):
                    os.remove(voice_response_file)
            else:
                await message.reply_text(bot_response)
