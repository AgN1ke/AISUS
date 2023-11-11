# message_wrapper.py
from pyrogram.types import Message


class MessageWrapper:
    def __init__(self, message: Message):
        self.message = message

    @property
    def chat_id(self):
        return self.message.chat.id

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
        return self.message.reply_to_message.from_user.username

    @property
    def from_user_first_name(self):
        return self.message.from_user.first_name

    @property
    def from_user_last_name(self):
        return self.message.from_user.last_name

    def download(self):
        return self.message.download()

    def reply_text(self, text: str):
        return self.message.reply_text(text)

    def reply_voice(self, voice):
        return self.message.reply_voice(voice)
