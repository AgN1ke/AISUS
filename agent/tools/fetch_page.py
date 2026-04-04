# agent/tools/fetch_page.py
from __future__ import annotations

import os
import re
import time
from typing import Optional

import requests

from db.search_repository import get_page_cache, put_page_cache

TTL_MIN = int(os.getenv("FETCH_TTL_MIN", "1440"))
TIMEOUT_SEC = int(os.getenv("FETCH_TIMEOUT_SEC", "10"))
USER_AGENTS = (
    "AISUSBot/1.0 (+https://example.local)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36",
)


def _request_headers() -> dict[str, str]:
    index = int(time.time()) % len(USER_AGENTS)
    return {"User-Agent": USER_AGENTS[index]}


def _clean_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    txt = soup.get_text(" ")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:20000]


async def fetch_page(url: str) -> str:
    cached = await get_page_cache(url, TTL_MIN)
    if cached:
        return cached
    resp = requests.get(url, headers=_request_headers(), timeout=TIMEOUT_SEC)
    resp.raise_for_status()
    text = _clean_text(resp.text)
    await put_page_cache(url, text)
    return text
