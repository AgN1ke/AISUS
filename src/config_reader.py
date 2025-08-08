class ConfigReader:
    def __init__(self, *args, **kwargs):
        self._system = {
            'welcome_message': '',
            'voice_message_affix': '',
            'image_message_affix': 'Ти отримав зображення.',
            'image_caption_affix': 'Під ним такий підпис відправника:',
            'image_sence_affix': 'На картинці зображено:',
            'password': ''
        }
        self._openai = {
            'api_key': '',
            'gpt_model': 'gpt-4o-mini',
            'whisper_model': '',
            'tts_model': '',
            'vocalizer_voice': ''
        }
        self._paths = {
            'audio_folder_path': '',
            'max_tokens': 0
        }

    def get_system_messages(self):
        return self._system

    def get_openai_settings(self):
        return self._openai

    def get_file_paths_and_limits(self):
        return self._paths
