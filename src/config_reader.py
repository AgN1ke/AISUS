from core.prompts import (
    LEGACY_DEFAULT_IMAGE_CAPTION_AFFIX,
    LEGACY_DEFAULT_IMAGE_MESSAGE_AFFIX,
    LEGACY_DEFAULT_IMAGE_SCENE_AFFIX,
)


class ConfigReader:
    def __init__(self, *args, **kwargs):
        self._system = {
            "welcome_message": "",
            "voice_message_affix": "",
            "image_message_affix": LEGACY_DEFAULT_IMAGE_MESSAGE_AFFIX,
            "image_caption_affix": LEGACY_DEFAULT_IMAGE_CAPTION_AFFIX,
            "image_sence_affix": LEGACY_DEFAULT_IMAGE_SCENE_AFFIX,
            "password": "",
        }
        self._openai = {
            "api_key": "",
            "gpt_model": "gpt-4o-mini",
            "whisper_model": "",
            "tts_model": "",
            "vocalizer_voice": "",
        }
        self._paths = {"audio_folder_path": "", "max_tokens": 0}

    def get_system_messages(self):
        return self._system

    def get_openai_settings(self):
        return self._openai

    def get_file_paths_and_limits(self):
        return self._paths
