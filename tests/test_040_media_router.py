from types import SimpleNamespace

import pytest

from media.router import handle_ptb_mention
from memory import memory_manager


class DummyMsg:
    def __init__(
        self,
        chat_id,
        mid,
        text=None,
        caption=None,
        reply_to=None,
        photo=None,
        video=None,
    ):
        self.message_id = mid
        self.chat_id = chat_id
        self.text = text
        self.caption = caption
        self.photo = photo or []
        self.video = video
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
    vid = tmp_path / "v.mp4"
    vid.write_text("vid")

    async def fake_download(msg, context):
        return {"type": "video", "paths": [str(vid)], "text": None}

    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr(
        "media.router.analyze_video",
        lambda p, task_hint=None: {
            "summary": "sum",
            "transcript": "",
            "frames": [],
            "vision_summary": "",
        },
    )

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


@pytest.mark.asyncio
async def test_reply_to_bot_with_current_photo_uses_current_message(monkeypatch):
    chat = 99906
    reply_to = DummyMsg(chat, 20, text="повідомлення бота")
    current = DummyMsg(chat, 21, text="поясни", reply_to=reply_to, photo=[object()])

    captured = {}

    async def fake_download(msg, context):
        captured["message_id"] = msg.message_id
        return {"type": "photo", "paths": [], "text": None}

    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr(
        "media.router.describe_images", lambda paths, task_hint=None: "img"
    )

    async def fake_append(*_args, **_kwargs):
        return None

    async def fake_budget(*_args, **_kwargs):
        return None

    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)

    upd = DummyUpdate(chat, current)
    await handle_ptb_mention(upd, DummyCtx, "mybot")

    assert captured["message_id"] == 21


@pytest.mark.asyncio
async def test_reply_to_media_text_prompt_uses_reply_target(monkeypatch):
    chat = 99907
    reply_to = DummyMsg(chat, 30, caption="мем", photo=[object()])
    current = DummyMsg(chat, 31, text="@mybot поясни мем", reply_to=reply_to)

    captured = {}

    async def fake_download(msg, context):
        captured["message_id"] = msg.message_id
        return {"type": "photo", "paths": [], "text": None}

    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr(
        "media.router.describe_images", lambda paths, task_hint=None: "img"
    )

    async def fake_append(*_args, **_kwargs):
        return None

    async def fake_budget(*_args, **_kwargs):
        return None

    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)

    upd = DummyUpdate(chat, current)
    txt = await handle_ptb_mention(upd, DummyCtx, "mybot")

    assert captured["message_id"] == 30
    assert "поясни мем" in txt
