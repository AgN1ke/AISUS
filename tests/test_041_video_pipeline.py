import os
from pathlib import Path
import pytest

from media import video as mv

@pytest.mark.asyncio
async def test_analyze_video_cleanup(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_text("vid")

    monkeypatch.setenv("CLEANUP_KEEP_WHISPER_TXT", "0")

    monkeypatch.setattr(mv, "_ffprobe_duration_sec", lambda p: 10)
    def fake_extract(src, dst, kbps=96):
        Path(dst).write_text("mp3")
    monkeypatch.setattr(mv, "_extract_audio_mp3", fake_extract)
    def fake_transcribe(mp3_path):
        txt = Path(mp3_path).with_suffix(".txt")
        txt.write_text("hello world")
        return "hello world"
    monkeypatch.setattr(mv, "transcribe_audio_mp3", fake_transcribe)
    def fake_sample(vpath, outdir, every_sec, max_frames):
        fdir = outdir / "frames"
        fdir.mkdir(parents=True, exist_ok=True)
        frame = fdir / "frame_00001.jpg"
        frame.write_text("img")
        return [str(frame)]
    monkeypatch.setattr(mv, "_sample_frames", fake_sample)
    monkeypatch.setattr(mv, "describe_images", lambda paths, task_hint=None: "vision")

    res = mv.analyze_video(str(video))
    assert res["vision_summary"] == "vision"
    assert "hello world" in res["summary"]
    assert not (tmp_path / "v_analysis").exists()
    assert not video.exists()


def test_analyze_video_too_long(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_text("vid")
    monkeypatch.setattr(mv, "_ffprobe_duration_sec", lambda p: 1000)
    with pytest.raises(RuntimeError):
        mv.analyze_video(str(video))
