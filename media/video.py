from __future__ import annotations
import os, subprocess, shlex, math
from pathlib import Path
from typing import List, Tuple
from pydub import AudioSegment

from media.vision import describe_images

VIDEO_MAX_SECONDS = int(os.getenv("VIDEO_MAX_SECONDS", "600"))
FRAME_EVERY_SEC = float(os.getenv("VIDEO_FRAME_EVERY_SEC", "2"))
VIDEO_MAX_FRAMES = int(os.getenv("VIDEO_MAX_FRAMES", "40"))

def _ffprobe_duration_sec(path: str) -> float:
    cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {shlex.quote(path)}'
    out = subprocess.check_output(cmd, shell=True, text=True).strip()
    try:
        return float(out)
    except Exception:
        return 0.0

def _extract_audio_mp3(video_path: str, out_mp3: str, kbps: int = 96) -> None:
    cmd = f'ffmpeg -y -i {shlex.quote(video_path)} -vn -acodec libmp3lame -b:a {kbps}k {shlex.quote(out_mp3)}'
    subprocess.check_call(cmd, shell=True)

def _sample_frames(video_path: str, out_dir: Path, every_sec: float, max_frames: int) -> List[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = max(0.1, 1.0 / max(0.1, every_sec))
    tmp_dir = out_dir / "frames"
    tmp_dir.mkdir(exist_ok=True)
    cmd = f'ffmpeg -y -i {shlex.quote(video_path)} -vf "fps={fps}" {shlex.quote(str(tmp_dir / "frame_%05d.jpg"))}'
    subprocess.check_call(cmd, shell=True)
    frames = sorted([str(p) for p in tmp_dir.glob("frame_*.jpg")])
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
    base = Path(video_path)
    workdir = base.parent / (base.stem + "_analysis")
    workdir.mkdir(exist_ok=True)

    dur = _ffprobe_duration_sec(video_path)
    if dur and dur > VIDEO_MAX_SECONDS:
        raise RuntimeError(f"Video too long: {dur:.0f}s > {VIDEO_MAX_SECONDS}s")

    mp3 = str(workdir / (base.stem + ".mp3"))
    _extract_audio_mp3(video_path, mp3)
    transcript = transcribe_audio_mp3(mp3)

    frames = _sample_frames(video_path, workdir, every_sec=FRAME_EVERY_SEC, max_frames=VIDEO_MAX_FRAMES)

    vision_summary = describe_images(frames, task_hint=task_hint)

    summary = (
        "Відео: короткий опис за кадрами та мовленням.\n\n"
        "Що бачимо (кадри):\n" + vision_summary + "\n\n"
        "Що чуємо (транскрипт, уривки):\n" + (transcript[:4000] if transcript else "—") + "\n"
    )

    return {
        "transcript": transcript,
        "frames": frames,
        "vision_summary": vision_summary,
        "summary": summary,
    }
