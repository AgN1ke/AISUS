# message_wrapper.py
import os
from typing import Optional
from telegram import Update


class MessageWrapper:
    def __init__(self, update: Update) -> None:
        self.update: Update = update
        self.message = update.message

    @property
    def chat_id(self) -> Optional[int]:
        return self.message.chat.id if self.message.chat else None

    @property
    def chat_type(self) -> Optional[str]:
        return self.message.chat.type if self.message.chat else None

    @property
    def text(self) -> Optional[str]:
        return self.message.text

    @property
    def voice(self):
        return self.message.voice

    @property
    def photo(self):
        return self.message.photo

    @property
    def reply_to_message(self):
        return self.message.reply_to_message

    @property
    def reply_to_message_from_user_username(self) -> Optional[str]:
        return self.message.reply_to_message.from_user.username if self.reply_to_message else None

    @property
    def from_user_first_name(self) -> str:
        return self.message.from_user.first_name

    @property
    def from_user_last_name(self) -> str:
        return self.message.from_user.last_name

    async def download_voice(self, download_dir: str) -> str:
        file = await self.message.voice.get_file()
        os.makedirs(download_dir, exist_ok=True)
        file_path: str = os.path.join(download_dir, f"{file.file_id}.ogg")
        await file.download_to_drive(file_path)
        return file_path

    async def download_image(self, download_dir: str) -> str:
        file = await self.message.photo[-1].get_file()
        os.makedirs(download_dir, exist_ok=True)
        file_path: str = os.path.join(download_dir, f"{file.file_id}.jpg")
        await file.download_to_drive(file_path)
        return file_path

    def reply_text(self, text: str):
        return self.message.reply_text(text, parse_mode='Markdown')

    def reply_voice(self, voice):
        return self.message.reply_voice(voice)
