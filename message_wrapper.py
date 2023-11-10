# message_wrapper.py
from pyrogram.types import Message as PyrogramMessage


class MessageWrapper:
    def __init__(self, message: PyrogramMessage):
        self._message = message

    @property
    def chat(self):
        return self._message.chat

    @property
    def text(self):
        return self._message.text

    @property
    def voice(self):
        return self._message.voice

    @property
    def from_user(self):
        return self._message.from_user

    @property
    def reply_to_message(self):
        return self._message.reply_to_message

    async def reply_voice(self, voice, *args, **kwargs):
        """Reply to the message with a voice message."""
        return await self._message.reply_voice(voice, *args, **kwargs)

    async def reply_text(self, text, *args, **kwargs):
        """Reply to the message with a text message."""
        return await self._message.reply_text(text, *args, **kwargs)

    async def download(self):
        return await self._message.download()
