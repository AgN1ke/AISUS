from __future__ import annotations

import base64
import mimetypes
from typing import List

from agent.llm import chat_once
from core.prompts import VISION_IMAGE_DESCRIPTION_PROMPT


def _img_to_data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def describe_images(paths: List[str], task_hint: str | None = None) -> str:
    """
    Returns a short combined description for one or more images.
    """
    parts = []
    for path in paths:
        parts.append(
            {"type": "image_url", "image_url": {"url": _img_to_data_url(path)}}
        )
    parts.insert(
        0,
        {
            "type": "text",
            "text": VISION_IMAGE_DESCRIPTION_PROMPT,
        },
    )

    messages = [{"role": "user", "content": parts}]
    if task_hint:
        messages.insert(0, {"role": "system", "content": task_hint})

    try:
        resp = chat_once(
            messages,
            tools=None,
            use_reasoning=False,
            model=None,
            temperature=0.2,
            capability="vision_image",
            max_tokens=1000,
        )
    except Exception:
        return ""
    return (resp.choices[0].message.content or "").strip()
