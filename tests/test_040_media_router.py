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

@pytest.mark.asyncio
async def test_video_mention_adds_media(monkeypatch, tmp_path):
    chat = 99905
    vid = tmp_path/"v.mp4"
    vid.write_text("vid")

    async def fake_download(msg, context):
        return {"type":"video", "paths":[str(vid)], "text":None}
    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr("media.router.analyze_video", lambda p, task_hint=None: {"summary":"sum","transcript":"","frames":[],"vision_summary":""})

    stored = {}
    async def fake_append(chat_id, role, content):
        stored["content"] = content
    async def fake_budget(chat_id):
        return None
    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)

    msg = DummyMsg(chat, 11, text="@mybot")
    upd = DummyUpdate(chat, msg)
    out = await handle_ptb_mention(upd, DummyCtx, "mybot")
    assert "[MEDIA]" in stored.get("content", "")
    assert "Проаналізуй" in out
