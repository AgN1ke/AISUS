"""Minimal stub of whisper_tool for testing purposes."""
from __future__ import annotations
from pathlib import Path

def transcribe(path: str):
    """Stub transcription: create empty .txt file next to path."""
    out = Path(path).with_suffix('.txt')
    out.write_text('', encoding='utf-8')
    return out
