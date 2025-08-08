# agent/runner.py
from __future__ import annotations
import os, json, traceback
from typing import List, Dict, Any, Optional

from agent.llm import tool_spec, make_messages, chat_once
from agent.tools.web_search import search_web
from agent.tools.fetch_page import fetch_page
from memory import memory_manager

THINKING_ENABLED = bool(int(os.getenv("THINKING_ENABLED", "1")))
SEARCH_ENABLED = bool(int(os.getenv("SEARCH_ENABLED", "1")))
MAX_STEPS = int(os.getenv("REASONING_MAX_STEPS", "3"))

SYSTEM_PROMPT_AGENT = (
    "Ти асистент-агент. Якщо бракує фактів або потрібна актуальна інформація — "
    "користуйся інструментами search_web та fetch_page. "
    "Не розкривай внутрішні кроки; пояснюй висновки лаконічно з посиланням на джерела (назва/домен)."
)

def _should_use_agent(user_text: str) -> bool:
    """
    Строгі тригери, якщо THINKING_STRICT=1:
    - явна команда /think
    - явні формулювання про веб-пошук/актуальність
    Якщо THINKING_STRICT=0 — поведінка м’якша (як раніше).
    """
    strict = bool(int(os.getenv("THINKING_STRICT", "1")))
    t = (user_text or "").strip().lower()

    hard_triggers = [
        "/think",
        "пошукай",
        "знайди в інтернеті",
        "перевір в інтернеті",
        "що нового",
        "новини",
    ]
    if any(k in t for k in hard_triggers):
        return True

    if strict:
        return False  # тільки явні тригери

    return bool(int(os.getenv("THINKING_ENABLED", "1")))

def _needs_reasoning(user_text: str) -> bool:
    """
    Використовуємо reasoning (gpt-5) тільки явним чином:
    - /think на початку
    - або є емодзі/слова: '🧠', 'роздумай', 'step-by-step'
    """
    t = (user_text or "").strip().lower()
    return t.startswith("/think") or ("🧠" in user_text) or ("роздумай" in t) or ("step-by-step" in t)

async def run_agent(chat_id: int, user_text: str) -> str:
    # 0) нормалізація: якщо є /think — прибираємо префікс із тексту
    raw = user_text or ""
    tnorm = raw.strip()
    if tnorm.lower().startswith("/think"):
        parts = tnorm.split(None, 1)
        user_text = parts[1] if len(parts) > 1 else ""
    else:
        user_text = tnorm

    # 1) контекст пам'яті (без системного, він нижче):
    ctx = await memory_manager.select_context(chat_id=chat_id, user_query=user_text, system_prompt=None)

    # 2) чи потрібен reasoning (gpt-5)?
    use_reasoning = _needs_reasoning(tnorm)

    # 3) первинний виклик з інструментами
    messages = make_messages(SYSTEM_PROMPT_AGENT, ctx, user_text)
    tools = tool_spec()
    used_sources: list[dict] = []

    resp = chat_once(messages, tools=tools, use_reasoning=use_reasoning)
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
        resp = chat_once(messages, tools=tools, use_reasoning=use_reasoning)
    final = resp.choices[0].message.content or "Не вдалося завершити міркування. Дай мені ще підказку."
    return final.strip()

async def run_simple(chat_id: int, user_text: str) -> str:
    ctx = await memory_manager.select_context(chat_id=chat_id, user_query=user_text, system_prompt=None)
    messages = make_messages("Ти корисний асистент.", ctx, user_text)
    resp = chat_once(messages, tools=None, use_reasoning=False)
    return (resp.choices[0].message.content or "").strip()
