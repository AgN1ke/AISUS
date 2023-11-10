# config_reader.py
import configparser


def _format_message(message):
    """Format the welcome and voice messages."""
    return message.replace(' | ', '\n')


class ConfigReader:
    def __init__(self, file_path):
        self.file_path = file_path
        self.config = self._read_config()

    def _read_config(self):
        """Read and parse the configuration file."""
        cfg = configparser.ConfigParser()
        cfg.read(self.file_path, encoding='utf-8')
        return cfg

    def get_system_messages(self):
        """Get and format system messages."""
        welcome_message = _format_message(self.config['system_messages']['welcome_message'])
        voice_message_afix = _format_message(self.config['system_messages']['voice_message_afix'])
        return {
            'welcome_message': welcome_message,
            'voice_message_afix': voice_message_afix
        }

    def get_openai_settings(self):
        """Get OpenAI API settings."""
        return {
            'api_key': self.config['openai']['api_key'],
            'gpt_model': self.config['openai']['gpt_model'],
            'whisper_model': self.config['openai']['whisper_model'],
            'tts_model': self.config['openai']['tts_model'],
            'vocalizer_voice': self.config['openai']['vocalizer_voice']
        }

    def get_api_settings(self):
        """Get other API settings."""
        return {
            'api_id': self.config['myapi']['api_id'],
            'api_hash': self.config['myapi']['api_hash'],
            'session_name': self.config['myapi']['session_name']
        }

    def get_file_paths_and_limits(self):
        """Get file paths and limits."""
        return {
            'audio_folder_path': self.config['file_paths']['audio_folder'],
            'max_tokens': int(self.config['limits']['max_tokens'])
        }
