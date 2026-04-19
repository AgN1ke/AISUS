from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from media import downloader


def test_cleanup_downloaded_media_sync_removes_files_and_empty_dirs(tmp_path, monkeypatch):
    media_root = tmp_path / "media_tmp"
    nested = media_root / "chat_1" / "sub"
    nested.mkdir(parents=True)
    payload = nested / "voice.ogg"
    payload.write_text("data", encoding="utf-8")

    monkeypatch.setattr(downloader, "MEDIA_TMP", media_root)

    downloader.cleanup_downloaded_media_sync([str(payload)])

    assert not payload.exists()
    assert not nested.exists()
    assert not (media_root / "chat_1").exists()


def test_purge_stale_media_tmp_sync_removes_old_files_keeps_fresh(tmp_path, monkeypatch):
    media_root = tmp_path / "media_tmp"
    media_root.mkdir(parents=True)
    stale = media_root / "old.jpg"
    fresh = media_root / "fresh.jpg"
    stale.write_text("old", encoding="utf-8")
    fresh.write_text("new", encoding="utf-8")

    old_time = time.time() - 3 * 3600
    os.utime(stale, (old_time, old_time))

    monkeypatch.setattr(downloader, "MEDIA_TMP", media_root)

    removed = downloader.purge_stale_media_tmp_sync(max_age_hours=1)

    assert removed == 1
    assert not stale.exists()
    assert fresh.exists()


@pytest.mark.asyncio
async def test_download_from_ptb_message_supports_video_note(tmp_path, monkeypatch):
    media_root = tmp_path / "media_tmp"
    media_root.mkdir(parents=True)
    monkeypatch.setattr(downloader, "MEDIA_TMP", media_root)

    class DummyFile:
        def __init__(self):
            self.saved_to = None

        async def download_to_drive(self, custom_path: str):
            self.saved_to = custom_path
            Path(custom_path).write_text("circle", encoding="utf-8")

    dummy_file = DummyFile()

    class DummyBot:
        async def get_file(self, file_id: str):
            assert file_id == "circle-file"
            return dummy_file

    context = type("Ctx", (), {"bot": DummyBot()})()
    message = type(
        "Msg",
        (),
        {
            "chat_id": 77,
            "message_id": 88,
            "text": None,
            "caption": "кружечок",
            "photo": [],
            "video": None,
            "video_note": type("VideoNote", (), {"file_id": "circle-file"})(),
            "voice": None,
            "audio": None,
            "document": None,
        },
    )()

    result = await downloader.download_from_ptb_message(message, context)

    assert result["type"] == "video"
    assert len(result["paths"]) == 1
    assert result["paths"][0].endswith("77_88.mp4")
    assert Path(result["paths"][0]).exists()
