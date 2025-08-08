# db/search_repository.py
from __future__ import annotations
import hashlib, json, datetime as dt
from typing import Optional, List, Dict
from .connection import fetchone, fetchall, execute

def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()

async def get_search_cache(provider: str, query: str, ttl_min: int) -> Optional[List[Dict]]:
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
    created = row["created_at"]
    if created and (dt.datetime.utcnow() - created).total_seconds() > ttl_min * 60:
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
    fetched = row["fetched_at"]
    if fetched and (dt.datetime.utcnow() - fetched).total_seconds() > ttl_min * 60:
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
