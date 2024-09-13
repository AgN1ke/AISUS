import os
from dotenv import load_dotenv



def _format_message(message):
    """Format the welcome and voice messages."""
    return message.replace(' | ', '\n')


class ConfigReader:
    def __init__(self):
        """Initialize the configuration from environment variables."""
        # System messages
        load_dotenv()
        self.welcome_message = _format_message(os.getenv('SYSTEM_MESSAGES_WELCOME_MESSAGE'))
        self.voice_message_affix = _format_message(os.getenv('SYSTEM_MESSAGES_VOICE_MESSAGE_AFFIX'))
        self.password = _format_message(os.getenv('PASSWORD'))

        # OpenAI settings
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.gpt_model = os.getenv('OPENAI_GPT_MODEL')
        self.whisper_model = os.getenv('OPENAI_WHISPER_MODEL')
        self.tts_model = os.getenv('OPENAI_TTS_MODEL')
        self.vocalizer_voice = os.getenv('OPENAI_VOCALIZER_VOICE')

        # MyAPI settings
        self.bot_token = os.getenv('MYAPI_BOT_TOKEN')

        # File paths
        self.audio_folder_path = os.getenv('FILE_PATHS_AUDIO_FOLDER')

        # Limits
        self.max_tokens = int(os.getenv('LIMITS_MAX_TOKENS', '0'))  # Default to 0 if not set

    def get_system_messages(self):
        """Return formatted system messages."""
        return {
            'welcome_message': self.welcome_message,
            'voice_message_affix': self.voice_message_affix,
            'password': self.password
        }

    def get_openai_settings(self):
        """Return OpenAI API settings."""
        return {
            'api_key': self.api_key,
            'gpt_model': self.gpt_model,
            'whisper_model': self.whisper_model,
            'tts_model': self.tts_model,
            'vocalizer_voice': self.vocalizer_voice
        }

    def get_api_settings(self):
        """Return API settings for the bot."""
        return {
            'bot_token': self.bot_token
        }

    def get_file_paths_and_limits(self):
        """Return file paths and limits."""
        return {
            'audio_folder_path': self.audio_folder_path,
            'max_tokens': self.max_tokens
        }

# Usage of the class would simply be instantiating and accessing the properties:
# config_reader = ConfigReader()
# print(config_reader.get_openai_settings())
