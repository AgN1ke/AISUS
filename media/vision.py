from __future__ import annotations
import os, base64, mimetypes
from typing import List
from openai import OpenAI

VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o-mini")
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or os.getenv("OPENAI_API_KEY_V1")
_client = OpenAI(api_key=_OPENAI_API_KEY) if _OPENAI_API_KEY else None

def _img_to_data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"

def describe_images(paths: List[str], task_hint: str | None = None) -> str:
    """
    Повертає коротке зведення про зображення/кадри одним текстом.
    """
    contents = []
    if task_hint:
        contents.append({"role": "user", "content": task_hint})
    parts = []
    for p in paths:
        parts.append({"type": "image_url", "image_url": {"url": _img_to_data_url(p)}})
    parts.insert(0, {"type": "text", "text": "Опиши зображення стисло, виділи текст на картинці, головних персонажів і дії."})

    if not _client:
        return ""
    resp = _client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{"role": "user", "content": parts}],
        temperature=0.2,
        max_tokens=400,
    )
    return (resp.choices[0].message.content or "").strip()
