import pytest
from types import SimpleNamespace
from knowledge.threads import handle_message_ptb
from knowledge.glossary import process_user_text
from db.knowledge_repository import get_thread, get_term

class DummyMsg:
    def __init__(self, chat_id, mid, reply_to=None, text="hi"):
        self.message_id = mid
        self.text = text
        self.caption = None
        self.photo = []
        self.voice = None
        self.video = None
        self.document = None
        self.reply_to_message = reply_to

class DummyUpdate:
    def __init__(self, chat_id, msg: DummyMsg):
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.effective_message = msg
        self.effective_user = SimpleNamespace(id=42)

@pytest.mark.asyncio
async def test_threads_and_glossary():
    chat = 99902
    root = DummyMsg(chat, 1, reply_to=None, text="root topic about rocket science")
    upd_root = DummyUpdate(chat, root)
    await handle_message_ptb(upd_root, None)

    child = DummyMsg(chat, 2, reply_to=root, text="reply with slang: lol kek cheburek")
    upd_child = DummyUpdate(chat, child)
    await handle_message_ptb(upd_child, None)

    thr = await get_thread(chat, 1)
    assert thr is not None

    await process_user_text(chat, "kek kek MEME42")
    term = await get_term(chat, "kek")
    assert term and term["usage_count"] >= 1
