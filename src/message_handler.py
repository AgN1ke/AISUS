# message_handler.py
from pyrogram.types import Message
from src.message_wrapper import MessageWrapper
from src.config_reader import ConfigReader
from pyrogram import Client, filters
from src.voice_processor import VoiceProcessor
from src.chat_history_manager import ChatHistoryManager
from src.openai_wrapper import OpenAIWrapper
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

    def handle_message(self, client, message: Message):
        wrapped_message = MessageWrapper(message)
        self._handle_message(client, wrapped_message)

    def _handle_message(self, client, message: MessageWrapper):
        """Handle incoming messages and generate responses."""
        if not self._should_process_message(client, message):
            return

        user_message, is_voice = self._process_message_content(message)
        if not user_message:
            return

        first_name, last_name = message.from_user_first_name, message.from_user_last_name
        chat_id = message.chat_id
        self._update_chat_history(chat_id, first_name, user_message, is_voice)

        bot_response = self._generate_bot_response(chat_id)
        self._send_response(message, bot_response, is_voice)
        self.chat_history_manager.add_bot_message(chat_id, bot_response)

        self.chat_history_manager.prune_history(chat_id, self.config.get_file_paths_and_limits()['max_tokens'])

    @staticmethod
    def _should_process_message(client, message):
        """Determine if the message should be processed."""
        bot_username = client.get_me().username
        return not (message.reply_to_message and
                    message.reply_to_message_from_user_username != bot_username and
                    (message.text is None or f"@{bot_username}" not in message.text))

    def _process_message_content(self, message):
        """Process the content of the message, whether it's voice or text."""
        if message.voice:
            voice_message_path = message.download()
            transcribed_text = self.voice_processor.transcribe_voice_message(voice_message_path)
            return transcribed_text, True
        else:
            return message.text, False

    def _update_chat_history(self, chat_id, first_name, user_message, is_voice):
        """Update the chat history with the user's message."""
        self.chat_history_manager.add_system_message(chat_id, self.config.get_system_messages()['welcome_message'])
        if is_voice:
            self.chat_history_manager.add_system_voice_affix_if_not_exist(
                chat_id, self.config.get_system_messages()['voice_message_affix'])
        else:
            self.chat_history_manager.remove_system_voice_affix_if_exist(
                chat_id, self.config.get_system_messages()['voice_message_affix'])
        self.chat_history_manager.add_user_message(chat_id, first_name, user_message)

    def _generate_bot_response(self, chat_id):
        """Generate the bot's response using OpenAI."""
        response = self.openai_wrapper.chat_completion(
            model=self.config.get_openai_settings()['gpt_model'],
            messages=self.chat_history_manager.get_history(chat_id),
            max_tokens=self.config.get_file_paths_and_limits()['max_tokens'])
        bot_response = response.choices[0].message.content
        return bot_response

    def _send_response(self, message, bot_response, is_voice):
        """Send the response back to the user."""
        if is_voice:
            voice_response_file = self.voice_processor.generate_voice_response_and_save_file(
                bot_response,
                self.config.get_openai_settings()['vocalizer_voice'],
                self.config.get_file_paths_and_limits()['audio_folder_path'])
            message.reply_voice(voice_response_file)
            if os.path.exists(voice_response_file):
                os.remove(voice_response_file)
        else:
            message.reply_text(bot_response)
