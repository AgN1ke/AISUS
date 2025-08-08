# agent/tools/web_search.py
from __future__ import annotations
import os, time, json, urllib.parse, requests
from typing import List, Dict, Optional
from db.search_repository import get_search_cache, put_search_cache
from bs4 import BeautifulSoup

PROVIDER = os.getenv("SEARCH_PROVIDER", "ddg").lower()
MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
TTL_MIN = int(os.getenv("SEARCH_TTL_MIN", "30"))

HEADERS = {
    "User-Agent": "AISUSBot/1.0 (+https://example.local)"
}

async def search_web(query: str, max_results: Optional[int] = None, recency_days: Optional[int] = None) -> List[Dict]:
    limit = min(max_results or MAX_RESULTS, 10)
    cached = await get_search_cache(PROVIDER, query, TTL_MIN)
    if cached:
        return cached[:limit]

    if PROVIDER == "bing" and os.getenv("BING_API_KEY"):
        url = "https://api.bing.microsoft.com/v7.0/search"
        params = {"q": query, "count": limit, "textDecorations": False, "textFormat": "Raw"}
        if recency_days:
            params["freshness"] = "Day" if recency_days <= 1 else "Week" if recency_days <= 7 else "Month"
        resp = requests.get(url, headers={"Ocp-Apim-Subscription-Key": os.getenv("BING_API_KEY"), **HEADERS}, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = []
        for it in (data.get("webPages", {}) or {}).get("value", [])[:limit]:
            items.append({"title": it.get("name",""), "url": it.get("url",""), "snippet": it.get("snippet","")})
    elif PROVIDER == "serper" and os.getenv("SERPER_API_KEY"):
        url = "https://google.serper.dev/search"
        body = {"q": query, "num": limit}
        if recency_days:
            body["tbs"] = f"qdr:{'d' if recency_days<=1 else 'w' if recency_days<=7 else 'm'}"
        resp = requests.post(url, headers={"X-API-KEY": os.getenv("SERPER_API_KEY"), "Content-Type":"application/json", **HEADERS}, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = []
        for it in (data.get("organic", []) or [])[:limit]:
            items.append({"title": it.get("title",""), "url": it.get("link",""), "snippet": it.get("snippet","")})
    elif PROVIDER == "tavily" and os.getenv("TAVILY_API_KEY"):
        url = "https://api.tavily.com/search"
        body = {"api_key": os.getenv("TAVILY_API_KEY"), "query": query, "max_results": limit}
        if recency_days:
            body["days"] = recency_days
        resp = requests.post(url, headers={"Content-Type":"application/json", **HEADERS}, json=body, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = []
        for it in (data.get("results", []) or [])[:limit]:
            items.append({"title": it.get("title",""), "url": it.get("url",""), "snippet": it.get("content","")})
    else:
        q = urllib.parse.quote_plus(query)
        url = f"https://duckduckgo.com/html/?q={q}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for a in soup.select("a.result__a")[:limit]:
            title = a.get_text(" ", strip=True)
            href = a.get("href")
            snippet = ""
            sn = a.find_parent("div", class_="result__body")
            if sn:
                snt = sn.find("a", class_="result__snippet")
                snippet = snt.get_text(" ", strip=True) if snt else ""
            items.append({"title": title, "url": href, "snippet": snippet})

    await put_search_cache(PROVIDER, query, items)
    return items
