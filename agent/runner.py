# agent/runner.py
from __future__ import annotations
import os, json, traceback
from typing import List, Dict, Any, Optional

from agent.llm import tool_spec, make_messages, chat_once
from agent.tools.web_search import search_web
from agent.tools.fetch_page import fetch_page
from memory import memory_manager

THINKING_ENABLED = bool(int(os.getenv("THINKING_ENABLED","1")))
SEARCH_ENABLED = bool(int(os.getenv("SEARCH_ENABLED","1")))
MAX_STEPS = int(os.getenv("REASONING_MAX_STEPS","3"))

SYSTEM_PROMPT_AGENT = (
    "Ти асистент-агент. Якщо бракує фактів або потрібна актуальна інформація — "
    "користуйся інструментами search_web та fetch_page. "
    "Не розкривай внутрішні кроки; пояснюй висновки лаконічно з посиланням на джерела (назва/домен)."
)

def _should_use_agent(user_text: str) -> bool:
    if not THINKING_ENABLED and not SEARCH_ENABLED:
        return False
    t = (user_text or "").lower()
    if t.startswith("/think") or "пошукай" in t or "знайди в інтернеті" in t or "що нового" in t:
        return True
    for kw in ["сьогодні", "вчора", "новини", "коли вийшло", "актуально"]:
        if kw in t:
            return True
    return THINKING_ENABLED

async def run_agent(chat_id: int, user_text: str) -> str:
    ctx = await memory_manager.select_context(chat_id=chat_id, user_query=user_text, system_prompt=None)
    messages = make_messages(SYSTEM_PROMPT_AGENT, ctx, user_text)
    tools = tool_spec()
    used_sources: list[dict] = []

    resp = chat_once(messages, tools=tools, use_reasoning=THINKING_ENABLED)
    step = 0
    while step < MAX_STEPS:
        step += 1
        choice = resp.choices[0]
        msg = choice.message
        if not msg.tool_calls:
            answer = (msg.content or "").strip()
            if used_sources:
                uniq = []
                seen = set()
                for s in used_sources:
                    dom = s.get("url","")
                    try:
                        import urllib.parse
                        dom = urllib.parse.urlparse(dom).netloc or dom
                    except Exception:
                        pass
                    key = (dom, s.get("title",""))
                    if key in seen:
                        continue
                    seen.add(key)
                    uniq.append(f"- {s.get('title') or dom} ({dom})")
                if uniq:
                    answer += "\n\nДжерела:\n" + "\n".join(uniq[:5])
            return answer
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            result_str = ""
            if name == "search_web" and SEARCH_ENABLED:
                res = await search_web(args.get("query",""), args.get("max_results"), args.get("recency_days"))
                for r in res:
                    used_sources.append(r)
                result_str = json.dumps(res, ensure_ascii=False)
            elif name == "fetch_page" and SEARCH_ENABLED:
                url = args.get("url","")
                text = await fetch_page(url)
                result_str = text
            else:
                result_str = f"TOOL_ERROR: unknown or disabled tool {name}"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": result_str[:20000],
            })
        resp = chat_once(messages, tools=tools, use_reasoning=THINKING_ENABLED)
    final = resp.choices[0].message.content or "Не вдалося завершити міркування. Дай мені ще підказку."
    return final.strip()

async def run_simple(chat_id: int, user_text: str) -> str:
    ctx = await memory_manager.select_context(chat_id=chat_id, user_query=user_text, system_prompt=None)
    messages = make_messages("Ти корисний асистент.", ctx, user_text)
    resp = chat_once(messages, tools=None, use_reasoning=False)
    return (resp.choices[0].message.content or "").strip()
