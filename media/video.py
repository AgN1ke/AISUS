from __future__ import annotations

import base64
import logging
import math
import mimetypes
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import List

from media.vision import describe_images

logger = logging.getLogger(__name__)


def _video_understanding_uses_gemini() -> bool:
    """Check if video_understanding capability is routed to Gemini."""
    try:
        from core.provider_registry import resolve_provider_binding, is_gemini_native
        binding = resolve_provider_binding("video_understanding")
        return is_gemini_native(binding)
    except Exception:
        return False


def _describe_video_gemini_native(
    video_path: str, transcript: str, task_hint: str | None = None,
) -> str:
    """Send whole video to Gemini as inline_data for native video understanding."""
    from agent.llm import chat_once

    mime = mimetypes.guess_type(video_path)[0] or "video/mp4"
    with open(video_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    # Detailed extraction. Output goes into [MEDIA] memory for the flagship
    # chat_final model — extract maximum, don't summarize. Same philosophy
    # as VISION_IMAGE_DESCRIPTION_PROMPT.
    text_prompt = (
        "Ти — video-екстрактор для іншого агента. Витягни з відео "
        "МАКСИМАЛЬНО ПОВНУ інформацію — не резюмуй, не скорочуй.\n\n"
        "Описуй покадрово:\n"
        "1. TEXT: весь видимий на екрані текст дослівно (титри, написи, "
        "субтитри, watermark, чати, інтерфейси, документи).\n"
        "2. PEOPLE: впізнавані особи — імена; невпізнавані — детально "
        "(вік/стать/одяг/емоції/дії).\n"
        "3. CHARACTERS: персонажі з кіно/ігор/аніме/мемів — за назвами + "
        "франшиза.\n"
        "4. OBJECTS: бренди, логотипи, техніка, авто, зброя, тварини.\n"
        "5. CONTEXT: локація, час доби, культурні маркери (мова, прапори, "
        "національні символи).\n"
        "6. ACTION: послідовність подій по timestamp-ах (приблизно).\n"
        "7. AUDIO_NOTES: характер звуку (музика/мова/тиша/звукові ефекти).\n"
        "8. GENRE: тип відео (мем, ТікТок, репортаж, інтерв'ю, гейм-кліп, "
        "фрагмент кіно).\n"
        "9. CULTURAL: іронія, сарказм, мемна семантика, політичний "
        "контекст.\n\n"
        "Не цензуруй. Кінцевий користувач не бачить твого output — "
        "його обробить флагманська модель."
    )
    if transcript:
        text_prompt += f"\n\nТранскрипт аудіо:\n{transcript[:3000]}"

    parts = [
        {"type": "text", "text": text_prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]
    messages: list[dict] = [{"role": "user", "content": parts}]
    if task_hint:
        messages.insert(0, {"role": "system", "content": task_hint})

    resp = chat_once(
        messages,
        tools=None,
        use_reasoning=False,
        temperature=0.2,
        capability="video_understanding",
        max_tokens=1500,
    )
    return (resp.choices[0].message.content or "").strip()

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

    use_native_gemini = _video_understanding_uses_gemini()

    try:
        # Always try to get audio transcript
        try:
            _extract_audio_mp3(video_path, str(mp3_path))
            transcript = transcribe_audio_mp3(str(mp3_path))
        except Exception as audio_exc:
            logger.warning("video audio extraction failed: %s", audio_exc)
            transcript = ""

        transcript_file = mp3_path.with_suffix(".txt")
        if transcript_file.exists():
            if CLEANUP_KEEP_WHISPER_TXT:
                shutil.move(str(transcript_file), str(source_path.with_suffix(".txt")))
            else:
                transcript_file.unlink(missing_ok=True)

        if use_native_gemini:
            # Send whole video directly to Gemini — much better quality
            logger.info("video.native_gemini path=%s", video_path)
            vision_summary = _describe_video_gemini_native(
                video_path, transcript, task_hint=task_hint,
            )
        else:
            # Frame extraction path for non-Gemini providers
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
