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
        media_group_id=None,
    ):
        self.message_id = mid
        self.chat_id = chat_id
        self.text = text
        self.caption = caption
        self.photo = photo or []
        self.video = video
        self.video_note = None
        self.voice = None
        self.audio = None
        self.document = None
        self.media_group_id = media_group_id
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
async def test_first_mention_with_text(monkeypatch):
    cleaned = []

    async def fake_append(*_args, **_kwargs):
        return None

    async def fake_budget(*_args, **_kwargs):
        return None

    async def fake_cleanup(paths):
        cleaned.append(list(paths))

    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)
    monkeypatch.setattr("media.router.cleanup_downloaded_media", fake_cleanup)

    chat = 99904
    msg = DummyMsg(chat, 10, text="@mybot do something")
    upd = DummyUpdate(chat, msg)
    txt, route_kind = await handle_ptb_mention(upd, DummyCtx, "mybot")
    assert "do something" in txt
    assert route_kind is None
    assert cleaned == [[]]


@pytest.mark.asyncio
async def test_video_mention_adds_media_transcript_and_cleans_downloads(
    monkeypatch, tmp_path
):
    chat = 99905
    vid = tmp_path / "v.mp4"
    vid.write_text("vid", encoding="utf-8")
    stored = {}
    cleaned = []

    async def fake_download(msg, context):
        del msg, context
        return {"type": "video", "paths": [str(vid)], "text": "post caption"}

    async def fake_append(chat_id, role, content):
        del chat_id, role
        stored["content"] = content

    async def fake_budget(chat_id):
        del chat_id
        return None

    async def fake_cleanup(paths):
        cleaned.append(list(paths))

    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr(
        "media.router.analyze_video",
        lambda p, task_hint=None: {
            "summary": "video summary",
            "transcript": "this is Sasha",
            "frames": [],
            "vision_summary": "",
        },
    )
    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)
    monkeypatch.setattr("media.router.cleanup_downloaded_media", fake_cleanup)

    msg = DummyMsg(chat, 11, text="@mybot")
    upd = DummyUpdate(chat, msg)
    out, route_kind = await handle_ptb_mention(upd, DummyCtx, "mybot")

    assert "[MEDIA]" in stored.get("content", "")
    assert "target_post_text: post caption" in stored.get("content", "")
    assert "audio_transcript: this is Sasha" in stored.get("content", "")
    assert "media_analysis: video summary" in stored.get("content", "")
    assert "Analyze" in out or "Проаналізуй" in out
    assert route_kind == "video"
    assert cleaned == [[str(vid)]]


@pytest.mark.asyncio
async def test_reply_to_bot_with_current_photo_uses_current_message(monkeypatch):
    chat = 99906
    reply_to = DummyMsg(chat, 20, text="bot message")
    current = DummyMsg(chat, 21, text="explain", reply_to=reply_to, photo=[object()])

    captured = {}
    cleaned = []

    async def fake_download(msg, context):
        del context
        captured["message_id"] = msg.message_id
        return {"type": "photo", "paths": ["fake.jpg"], "text": "meme caption"}

    async def fake_append(_chat_id, _role, _content):
        return None

    async def fake_budget(*_args, **_kwargs):
        return None

    async def fake_cleanup(paths):
        cleaned.append(list(paths))

    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr("media.router.describe_images", lambda paths, task_hint=None: "img")
    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)
    monkeypatch.setattr("media.router.cleanup_downloaded_media", fake_cleanup)

    upd = DummyUpdate(chat, current)
    _text, route_kind = await handle_ptb_mention(upd, DummyCtx, "mybot")

    assert captured["message_id"] == 21
    assert route_kind == "image"
    assert cleaned == [["fake.jpg"]]


@pytest.mark.asyncio
async def test_reply_to_media_text_prompt_uses_reply_target(monkeypatch):
    chat = 99907
    reply_to = DummyMsg(chat, 30, caption="meme", photo=[object()])
    current = DummyMsg(chat, 31, text="@mybot explain meme", reply_to=reply_to)

    captured = {}
    stored = {}
    cleaned = []

    async def fake_download(msg, context):
        del context
        captured["message_id"] = msg.message_id
        return {"type": "photo", "paths": ["fake.jpg"], "text": "meme caption"}

    async def fake_append(_chat_id, _role, content):
        stored["content"] = content

    async def fake_budget(*_args, **_kwargs):
        return None

    async def fake_cleanup(paths):
        cleaned.append(list(paths))

    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr("media.router.describe_images", lambda paths, task_hint=None: "img")
    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)
    monkeypatch.setattr("media.router.cleanup_downloaded_media", fake_cleanup)

    upd = DummyUpdate(chat, current)
    txt, route_kind = await handle_ptb_mention(upd, DummyCtx, "mybot")

    assert captured["message_id"] == 30
    assert "explain meme" in txt
    assert route_kind == "image"
    assert "target_post_text: meme caption" in stored["content"]
    assert "media_analysis: img" in stored["content"]
    assert cleaned == [["fake.jpg"]]


@pytest.mark.asyncio
async def test_reply_to_video_text_prompt_uses_reply_target_and_keeps_transcript(
    monkeypatch,
):
    chat = 99909
    reply_to = DummyMsg(chat, 40, caption="video from Sasha", video=object())
    current = DummyMsg(chat, 41, text="@mybot what is his name", reply_to=reply_to)

    captured = {}
    stored = {}
    cleaned = []

    async def fake_download(msg, context):
        del context
        captured["message_id"] = msg.message_id
        return {
            "type": "video",
            "paths": ["fake.mp4"],
            "text": "video from Sasha",
        }

    async def fake_append(_chat_id, _role, content):
        stored["content"] = content

    async def fake_budget(*_args, **_kwargs):
        return None

    async def fake_cleanup(paths):
        cleaned.append(list(paths))

    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr(
        "media.router.analyze_video",
        lambda path, task_hint=None: {
            "summary": "A young man is speaking on camera",
            "transcript": "My name is Oleksandr",
            "frames": [],
            "vision_summary": "",
        },
    )
    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)
    monkeypatch.setattr("media.router.cleanup_downloaded_media", fake_cleanup)

    upd = DummyUpdate(chat, current)
    txt, route_kind = await handle_ptb_mention(upd, DummyCtx, "mybot")

    assert captured["message_id"] == 40
    assert "what is his name" in txt
    assert route_kind == "video"
    assert "target_post_text: video from Sasha" in stored["content"]
    assert "audio_transcript: My name is Oleksandr" in stored["content"]
    assert "media_analysis: A young man is speaking on camera" in stored["content"]
    assert cleaned == [["fake.mp4"]]


@pytest.mark.asyncio
async def test_voice_mention_adds_transcript_and_post_text(monkeypatch):
    chat = 99908
    stored = {}
    cleaned = []

    async def fake_download(msg, context):
        del msg, context
        return {
            "type": "voice",
            "paths": ["fake.ogg"],
            "text": "voice caption",
        }

    async def fake_transcribe(_path):
        return "hello, this is a test transcript"

    async def fake_append(_chat_id, _role, content):
        stored["content"] = content

    async def fake_budget(*_args, **_kwargs):
        return None

    async def fake_cleanup(paths):
        cleaned.append(list(paths))

    monkeypatch.setattr("media.router.download_from_ptb_message", fake_download)
    monkeypatch.setattr("media.router.transcribe_audio", fake_transcribe)
    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)
    monkeypatch.setattr("media.router.cleanup_downloaded_media", fake_cleanup)

    msg = DummyMsg(chat, 32, text="@mybot")
    msg.voice = object()
    upd = DummyUpdate(chat, msg)
    out, route_kind = await handle_ptb_mention(upd, DummyCtx, "mybot")

    assert "target_post_text: voice caption" in stored["content"]
    assert "audio_transcript: hello, this is a test transcript" in stored["content"]
    assert out == "hello, this is a test transcript"
    assert route_kind == "voice"
    assert cleaned == [["fake.ogg"]]


@pytest.mark.asyncio
async def test_reply_to_album_builds_album_bundle_with_all_items(monkeypatch):
    chat = 99910
    reply_to = DummyMsg(
        chat,
        50,
        caption="album caption",
        photo=[object()],
        media_group_id="album-1",
    )
    current = DummyMsg(chat, 51, text="@mybot who is in this album", reply_to=reply_to)

    stored = {}
    cleaned = []

    async def fake_download_album(messages, context):
        del context
        assert [message.message_id for message in messages] == [50, 52]
        return {
            "type": "album",
            "group_id": "album-1",
            "route_kind": "video",
            "text": "album caption",
            "paths": ["1.jpg", "2.mp4"],
            "items": [
                {"type": "photo", "paths": ["1.jpg"], "text": "album caption", "message_id": 50},
                {"type": "video", "paths": ["2.mp4"], "text": "", "message_id": 52},
            ],
        }

    async def fake_append(_chat_id, _role, content):
        stored["content"] = content

    async def fake_budget(*_args, **_kwargs):
        return None

    async def fake_cleanup(paths):
        cleaned.append(list(paths))

    monkeypatch.setattr("media.router.get_ptb_album_messages", lambda target: [reply_to, DummyMsg(chat, 52, video=object(), media_group_id="album-1")])
    monkeypatch.setattr("media.router.download_from_ptb_album", fake_download_album)
    monkeypatch.setattr("media.router.describe_images", lambda paths, task_hint=None: "first image shows Sasha")
    monkeypatch.setattr(
        "media.router.analyze_video",
        lambda path, task_hint=None: {
            "summary": "second item is a short video selfie",
            "transcript": "my name is Sasha",
            "frames": [],
            "vision_summary": "",
        },
    )
    monkeypatch.setattr(memory_manager, "append_message", fake_append)
    monkeypatch.setattr(memory_manager, "ensure_budget", fake_budget)
    monkeypatch.setattr("media.router.cleanup_downloaded_media", fake_cleanup)

    upd = DummyUpdate(chat, current)
    out, route_kind = await handle_ptb_mention(upd, DummyCtx, "mybot")

    assert "who is in this album" in out
    assert route_kind == "video"
    assert "target_media_type: album" in stored["content"]
    assert "album_item_count: 2" in stored["content"]
    assert "album_route_media_kind: video" in stored["content"]
    assert "target_post_text: album caption" in stored["content"]
    assert "album_item_1_type: photo" in stored["content"]
    assert "album_item_1_media_analysis: first image shows Sasha" in stored["content"]
    assert "album_item_2_type: video" in stored["content"]
    assert "album_item_2_audio_transcript: my name is Sasha" in stored["content"]
    assert "album_item_2_media_analysis: second item is a short video selfie" in stored["content"]
    assert cleaned == [["1.jpg", "2.mp4"]]
