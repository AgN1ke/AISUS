# db/search_repository.py
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Dict, List, Optional

from .connection import execute, fetchone


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ensure_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _is_expired(created_at: dt.datetime | None, ttl_min: int) -> bool:
    normalized = _ensure_utc(created_at)
    if normalized is None:
        return False
    return (_utcnow() - normalized).total_seconds() > ttl_min * 60


async def get_search_cache(
    provider: str, query: str, ttl_min: int
) -> Optional[List[Dict]]:
    qh = _h(query.strip().lower())
    row = await fetchone(
        """
      SELECT results_json, created_at FROM search_cache
      WHERE provider=%s AND query_hash=%s
      ORDER BY id DESC LIMIT 1
    """,
        (provider, qh),
    )
    if not row:
        return None
    if _is_expired(row["created_at"], ttl_min):
        return None
    try:
        return json.loads(row["results_json"])
    except Exception:
        return None


async def put_search_cache(provider: str, query: str, results: List[Dict]):
    qh = _h(query.strip().lower())
    await execute(
        """
      INSERT INTO search_cache (provider, query_hash, query_text, results_json)
      VALUES (%s,%s,%s,%s)
    """,
        (provider, qh, query, json.dumps(results, ensure_ascii=False)),
    )


async def get_page_cache(url: str, ttl_min: int) -> Optional[str]:
    uh = _h(url)
    row = await fetchone(
        """
      SELECT text, fetched_at FROM page_cache WHERE url_hash=%s
      ORDER BY id DESC LIMIT 1
    """,
        (uh,),
    )
    if not row:
        return None
    if _is_expired(row["fetched_at"], ttl_min):
        return None
    return row["text"]


async def put_page_cache(url: str, text: str):
    uh = _h(url)
    await execute(
        """
      INSERT INTO page_cache (url_hash, url, text) VALUES (%s,%s,%s)
    """,
        (uh, url, text),
    )
