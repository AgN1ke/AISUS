import pytest
from types import SimpleNamespace
from media.router import handle_ptb_mention
from memory import memory_manager

class DummyMsg:
    def __init__(self, chat_id, mid, text=None, caption=None, reply_to=None):
        self.message_id = mid
        self.text = text
        self.caption = caption
        self.photo = []
        self.video = None
        self.voice = None
        self.audio = None
        self.document = None
        self.reply_to_message = reply_to
        self.entities = []
        self.caption_entities = []

class DummyUpdate:
    def __init__(self, chat_id, msg):
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.effective_message = msg

class DummyCtx:
    bot = SimpleNamespace(username="mybot")

@pytest.mark.asyncio
async def test_first_mention_with_text():
    chat = 99904
    msg = DummyMsg(chat, 10, text="@mybot зроби щось")
    upd = DummyUpdate(chat, msg)
    txt = await handle_ptb_mention(upd, DummyCtx, "mybot")
    assert "зроби" in txt
