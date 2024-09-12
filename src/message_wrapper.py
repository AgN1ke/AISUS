import os
from telegram import Update

class MessageWrapper:
    def __init__(self, update: Update):
        self.update = update
        self.message = update.message

    @property
    def chat_id(self):
        return self.message.chat.id if self.message.chat else None

    @property
    def chat_type(self):
        return self.message.chat.type if self.message.chat else None

    @property
    def text(self):
        return self.message.text

    @property
    def voice(self):
        return self.message.voice

    @property
    def reply_to_message(self):
        return self.message.reply_to_message

    @property
    def reply_to_message_from_user_username(self):
        return self.message.reply_to_message.from_user.username if self.reply_to_message else None

    @property
    def from_user_first_name(self):
        return self.message.from_user.first_name

    @property
    def from_user_last_name(self):
        return self.message.from_user.last_name

    async def download(self):
        file = await self.message.voice.get_file()
        file_path = os.path.join(os.getcwd(), f"{file.file_id}.ogg")
        await file.download_to_drive(file_path)
        return file_path

    def reply_text(self, text: str):
        return self.message.reply_text(text, parse_mode='MarkdownV2')

    def reply_voice(self, voice):
        return self.message.reply_voice(voice)
