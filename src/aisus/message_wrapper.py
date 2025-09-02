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
        return self.message.chat.id if self.message and self.message.chat else None

    @property
    def chat_type(self) -> Optional[str]:
        return self.message.chat.type if self.message and self.message.chat else None

    @property
    def text(self) -> Optional[str]:
        return self.message.text if self.message else None

    @property
    def caption(self) -> Optional[str]:
        return self.message.caption if self.message else None

    @property
    def voice(self):
        return self.message.voice if self.message else None

    @property
    def photo(self):
        return self.message.photo if self.message else None

    @property
    def document(self):
        return self.message.document if self.message else None

    @property
    def reply_to_message(self):
        return self.message.reply_to_message if self.message else None

    @property
    def reply_to_message_from_user_username(self) -> Optional[str]:
        m = self.reply_to_message
        return m.from_user.username if m and m.from_user else None

    @property
    def from_user_first_name(self) -> str:
        return self.message.from_user.first_name if self.message and self.message.from_user else ""

    @property
    def from_user_last_name(self) -> str:
        return self.message.from_user.last_name if self.message and self.message.from_user else ""

    async def download_voice(self, download_dir: str) -> str:
        f = await self.message.voice.get_file()
        os.makedirs(download_dir, exist_ok=True)
        path: str = os.path.join(download_dir, f"{self.message.voice.file_unique_id}.ogg")
        await f.download_to_drive(path)
        return path

    async def download_image(self, download_dir: str) -> str:
        img = self.message.photo[-1]
        f = await img.get_file()
        os.makedirs(download_dir, exist_ok=True)
        path: str = os.path.join(download_dir, f"img_{img.file_unique_id}.jpg")
        await f.download_to_drive(path)
        return path

    async def download_document(self, download_dir: str) -> str:
        doc = self.message.document
        f = await doc.get_file()
        os.makedirs(download_dir, exist_ok=True)
        filename = doc.file_name or f"doc_{doc.file_unique_id}"
        path: str = os.path.join(download_dir, filename)
        await f.download_to_drive(path)
        return path

    async def reply_text(self, text: str):
        return await self.message.reply_text(text, parse_mode="Markdown")

    async def reply_voice(self, voice):
        return await self.message.reply_voice(voice)
