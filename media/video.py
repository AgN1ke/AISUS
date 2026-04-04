from __future__ import annotations

import logging
import math
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import List

from media.vision import describe_images

logger = logging.getLogger(__name__)

VIDEO_MAX_SECONDS = int(os.getenv("VIDEO_MAX_SECONDS", "600"))
FRAME_EVERY_SEC = float(os.getenv("VIDEO_FRAME_EVERY_SEC", "2"))
VIDEO_MAX_FRAMES = int(os.getenv("VIDEO_MAX_FRAMES", "40"))
FFMPEG_DIR = os.getenv("FFMPEG_DIR") or ""
FFMPEG_BIN = os.path.join(FFMPEG_DIR, "ffmpeg") if FFMPEG_DIR else "ffmpeg"
FFPROBE_BIN = os.path.join(FFMPEG_DIR, "ffprobe") if FFMPEG_DIR else "ffprobe"
CLEANUP_KEEP_WHISPER_TXT = bool(int(os.getenv("CLEANUP_KEEP_WHISPER_TXT", "1")))


def _ffprobe_duration_sec(path: str) -> float:
    cmd = (
        f"{FFPROBE_BIN} -v error -show_entries format=duration "
        f"-of default=noprint_wrappers=1:nokey=1 {shlex.quote(path)}"
    )
    try:
        out = subprocess.check_output(cmd, shell=True, text=True).strip()
        return float(out)
    except Exception as exc:
        logger.error("ffprobe failed for %s: %s", path, exc, exc_info=True)
        return 0.0


def _extract_audio_mp3(video_path: str, out_mp3: str, kbps: int = 96) -> None:
    cmd = (
        f"{FFMPEG_BIN} -y -i {shlex.quote(video_path)} -vn "
        f"-acodec libmp3lame -b:a {kbps}k {shlex.quote(out_mp3)}"
    )
    subprocess.check_call(cmd, shell=True)


def _sample_frames(
    video_path: str, out_dir: Path, every_sec: float, max_frames: int
) -> List[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = max(0.1, 1.0 / max(0.1, every_sec))
    frame_dir = out_dir / "frames"
    frame_dir.mkdir(exist_ok=True)

    cmd = (
        f"{FFMPEG_BIN} -y -i {shlex.quote(video_path)} "
        f"-vf 'fps={fps}' {shlex.quote(str(frame_dir / 'frame_%05d.jpg'))}"
    )
    subprocess.check_call(cmd, shell=True)

    frames = sorted(str(path) for path in frame_dir.glob("frame_*.jpg"))
    if len(frames) > max_frames:
        step = math.ceil(len(frames) / max_frames)
        frames = frames[::step][:max_frames]
    return frames


def transcribe_audio_mp3(mp3_path: str) -> str:
    from whisper_tool import transcribe as wt_transcribe

    wt_transcribe(mp3_path)
    txt_path = Path(mp3_path).with_suffix(".txt")
    return txt_path.read_text(encoding="utf-8") if txt_path.exists() else ""


def analyze_video(video_path: str, task_hint: str | None = None) -> dict:
    source_path = Path(video_path)
    workdir = source_path.parent / f"{source_path.stem}_analysis"
    workdir.mkdir(exist_ok=True)

    duration = _ffprobe_duration_sec(video_path)
    if duration and duration > VIDEO_MAX_SECONDS:
        raise RuntimeError(f"Video too long: {duration:.0f}s > {VIDEO_MAX_SECONDS}s")

    mp3_path = workdir / f"{source_path.stem}.mp3"
    transcript = ""
    frames: List[str] = []
    vision_summary = ""

    try:
        _extract_audio_mp3(video_path, str(mp3_path))
        transcript = transcribe_audio_mp3(str(mp3_path))

        transcript_file = mp3_path.with_suffix(".txt")
        if transcript_file.exists():
            if CLEANUP_KEEP_WHISPER_TXT:
                shutil.move(str(transcript_file), str(source_path.with_suffix(".txt")))
            else:
                transcript_file.unlink(missing_ok=True)

        frames = _sample_frames(
            video_path, workdir, every_sec=FRAME_EVERY_SEC, max_frames=VIDEO_MAX_FRAMES
        )
        vision_summary = describe_images(frames, task_hint=task_hint)
    except Exception as exc:
        logger.error("video analysis failed for %s: %s", video_path, exc, exc_info=True)
        raise
    finally:
        if mp3_path.exists():
            mp3_path.unlink(missing_ok=True)
        shutil.rmtree(workdir, ignore_errors=True)
        if source_path.exists():
            source_path.unlink(missing_ok=True)

    summary = (
        "Відео: короткий опис за кадрами та мовленням.\n\n"
        "Що бачимо (кадри):\n" + (vision_summary or "—") + "\n\n"
        "Що чуємо (транскрипт, уривки):\n"
        + (transcript[:4000] if transcript else "—")
        + "\n"
    )

    return {
        "transcript": transcript,
        "frames": frames,
        "vision_summary": vision_summary,
        "summary": summary,
    }
