# knowledge/glossary.py
from __future__ import annotations
import os, re, time
from typing import List, Optional, Tuple, Dict
from db.knowledge_repository import upsert_term, get_term, fetch_gc_candidates

GLOSSARY_ENABLE_SUGGESTIONS = bool(int(os.getenv("GLOSSARY_ENABLE_SUGGESTIONS", "0")))
GLOSSARY_MIN_USAGE_TO_ASK = int(os.getenv("GLOSSARY_MIN_USAGE_TO_ASK", "5"))

_LAST_SUGGEST_AT: Dict[int, float] = {}

_STOPWORDS = set("""
і та але або що це тут там той ця це ті тієї через дуже трохи для при над під між як коли де який яка які було були бути буде уже вже ще той-то ось ну ага ого не так таке така такий such the and or of to in on a an is are was were be been have has had with without from by about for into over under out up down just really very they them he she it we you me i my your his her their our у в на до із з зі і та але або що це тут там той ця ті тієї для при над під між як коли де який яка які
""".split())

def _normalize(token: str) -> Optional[str]:
    token = token.strip().lower()
    if len(token) < 3:
        return None
    if not re.match(r"^[\w\-]+$", token, flags=re.U):
        return None
    if token in _STOPWORDS:
        return None
    return token

def extract_terms(text: str) -> List[str]:
    if not text:
        return []
    raw = re.findall(r"[\w\-]+", text, flags=re.U)
    terms = []
    for w in raw:
        n = _normalize(w)
        if n:
            terms.append(n)
    seen = set()
    res = []
    for t in terms:
        if t not in seen:
            res.append(t)
            seen.add(t)
    return res

async def process_user_text(chat_id: int, text: str) -> Optional[str]:
    terms = extract_terms(text)
    if not terms:
        return None

    for t in terms:
        await upsert_term(chat_id, t, inc=1)

    if not GLOSSARY_ENABLE_SUGGESTIONS:
        return None

    now = time.time()
    if now - _LAST_SUGGEST_AT.get(chat_id, 0) < 120:
        return None

    for t in terms:
        row = await get_term(chat_id, t)
        if not row:
            continue
        if (row.get("usage_count") or 0) >= GLOSSARY_MIN_USAGE_TO_ASK and (row.get("status") or "new") == "new":
            _LAST_SUGGEST_AT[chat_id] = now
            return (f"Бачу, термін «{t}» часто вживається. "
                    f"Дати коротке визначення і зберегти в глосарії? Напиши: «{t} — <визначення>».")
    return None

async def gc_suggestions(chat_id: int) -> Optional[str]:
    olds = await fetch_gc_candidates(chat_id, idle_days=45, limit=5)
    if not olds:
        return None
    names = ", ".join([o["term"] for o in olds])
    return f"Схоже, терміни давно не використовувались: {names}. Архівувати?"
