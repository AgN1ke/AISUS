# agent/llm.py
from __future__ import annotations
import os, json
from typing import List, Dict, Any, Optional
from openai import OpenAI

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or os.getenv("OPENAI_API_KEY_V1")
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5-chat-latest")
REASONING_MODEL = os.getenv("OPENAI_REASONING_MODEL", "gpt-5")  # <-- default reasoning model
REASONING_EFFORT = os.getenv("REASONING_EFFORT", "medium")

_client: Optional[OpenAI] = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not _OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=_OPENAI_API_KEY)
    return _client

def _maybe_reasoning_args():
    if not REASONING_MODEL:
        return {}
    return {"reasoning": {"effort": REASONING_EFFORT}}

def _pick_model(reasoning: bool) -> str:
    if reasoning and REASONING_MODEL:
        return REASONING_MODEL
    return CHAT_MODEL

def tool_spec() -> List[Dict[str, Any]]:
    return [
        {
          "type": "function",
          "function": {
            "name": "search_web",
            "description": "Веб-пошук актуальної інформації. Повертає список результатів (title, url, snippet).",
            "parameters": {
              "type": "object",
              "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
                "recency_days": {"type": "integer"}
              },
              "required": ["query"]
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "fetch_page",
            "description": "Завантажити сторінку за URL і повернути очищений текст.",
            "parameters": {
              "type": "object",
              "properties": {
                "url": {"type": "string"}
              },
              "required": ["url"]
            }
          }
        }
    ]

def make_messages(system_prompt: str, context_msgs: List[Dict[str,str]], user_msg: str) -> List[Dict[str,str]]:
    msgs: List[Dict[str,str]] = []
    if system_prompt:
        msgs.append({"role":"system","content": system_prompt})
    msgs.extend(context_msgs)
    if user_msg:
        msgs.append({"role":"user","content": user_msg})
    return msgs

def chat_once(messages: List[Dict[str, str]], tools: Optional[List[Dict[str, Any]]] = None, use_reasoning: bool = False):
    kwargs = {
        "model": _pick_model(use_reasoning),
        "messages": messages,
        "temperature": 0.3,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if use_reasoning:
        kwargs.update(_maybe_reasoning_args())
    client = _get_client()
    return client.chat.completions.create(**kwargs)
