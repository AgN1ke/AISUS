# agent/tools/fetch_page.py
from __future__ import annotations
import re, os, requests
from typing import Optional
from bs4 import BeautifulSoup
from db.search_repository import get_page_cache, put_page_cache

TTL_MIN = int(os.getenv("FETCH_TTL_MIN", "1440"))
HEADERS = {"User-Agent": "AISUSBot/1.0 (+https://example.local)"}

def _clean_text(html: str) -> str:
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
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    text = _clean_text(resp.text)
    await put_page_cache(url, text)
    return text
