from __future__ import annotations

import re
import time
from functools import lru_cache
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI

from core.env import (
    GEMINI_DEFAULT_BASE_URL,
    gemini_thinking_budget,
    provider_supports_reasoning,
    reasoning_effort,
    reasoning_model,
)
from core.provider_registry import (
    ProviderBinding,
    is_gemini_native,
    is_openai_compatible,
    resolve_provider_binding,
)

_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$",
    flags=re.I | re.S,
)


def _resolve_binding(
    capability: str,
    model_override: Optional[str] = None,
) -> ProviderBinding:
    return resolve_provider_binding(capability, model=model_override)


@lru_cache(maxsize=32)
def get_llm_client(
    provider: str,
    api_key: str,
    base_url: str | None = None,
) -> OpenAI:
    if not api_key:
        raise RuntimeError(f"API key is not configured for provider '{provider}'")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def clear_llm_client_cache() -> None:
    cache_clear = getattr(get_llm_client, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


def _get_client(binding: ProviderBinding) -> OpenAI:
    if not is_openai_compatible(binding):
        raise RuntimeError(
            f"Unsupported adapter for capability '{binding.capability}': {binding.adapter}"
        )
    return get_llm_client(binding.provider, binding.api_key or "", binding.base_url)


def _maybe_reasoning_args(capability: str, use_reasoning: bool) -> dict:
    current_reasoning_model = reasoning_model()
    if not use_reasoning or not current_reasoning_model:
        return {}
    binding = _resolve_binding(capability)
    if not is_openai_compatible(binding):
        return {}
    provider = binding.provider
    if not provider_supports_reasoning(provider):
        return {}
    return {"reasoning": {"effort": reasoning_effort()}}


def _pick_model(
    binding: ProviderBinding,
    reasoning: bool,
    model_override: Optional[str] = None,
) -> str:
    if model_override:
        return binding.model
    current_reasoning_model = reasoning_model()
    if (
        reasoning
        and current_reasoning_model
        and is_openai_compatible(binding)
        and provider_supports_reasoning(binding.provider)
    ):
        return current_reasoning_model
    return binding.model


def _response_with_content(text: str):
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _text_from_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    chunks.append(text)
                continue
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text = str(item.get("text") or "").strip()
                    if text:
                        chunks.append(text)
                    continue
                if "text" in item:
                    text = str(item.get("text") or "").strip()
                    if text:
                        chunks.append(text)
        return "\n".join(chunks).strip()
    return str(content).strip()


def _data_url_to_inline_data(url: str) -> dict:
    match = _DATA_URL_RE.match((url or "").strip())
    if not match:
        raise RuntimeError(
            "Gemini adapter currently supports only data URL images for inline media."
        )
    return {
        "mime_type": match.group("mime"),
        "data": match.group("data"),
    }


def _parts_to_gemini(content: Any) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        text = content.strip()
        return [{"text": text}] if text else []
    if isinstance(content, dict):
        return _parts_to_gemini([content])
    if not isinstance(content, list):
        text = str(content).strip()
        return [{"text": text}] if text else []

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            text = item.strip()
            if text:
                parts.append({"text": text})
            continue
        if not isinstance(item, dict):
            text = str(item).strip()
            if text:
                parts.append({"text": text})
            continue

        part_type = (item.get("type") or "").strip().lower()
        if part_type == "text" or ("text" in item and not part_type):
            text = str(item.get("text") or "").strip()
            if text:
                parts.append({"text": text})
            continue

        if part_type == "image_url":
            image_url = item.get("image_url") or {}
            url = (
                image_url if isinstance(image_url, str) else image_url.get("url") or ""
            )
            parts.append({"inline_data": _data_url_to_inline_data(url)})
            continue

        raise RuntimeError(
            f"Unsupported Gemini content part type: {part_type or 'unknown'}"
        )
    return parts


def _messages_to_gemini_payload(
    messages: List[Dict[str, Any]],
    *,
    temperature: float,
    max_tokens: int | None,
    model: str,
) -> dict[str, Any]:
    system_texts: list[str] = []
    contents: list[dict[str, Any]] = []

    for message in messages:
        role = (message.get("role") or "user").strip().lower()
        if role == "tool" or message.get("tool_calls"):
            raise RuntimeError(
                "Gemini adapter does not yet support tool calls or tool messages."
            )

        if role == "system":
            text = _text_from_content(message.get("content"))
            if text:
                system_texts.append(text)
            continue

        parts = _parts_to_gemini(message.get("content"))
        if not parts:
            continue

        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": parts,
            }
        )

    if not contents:
        raise RuntimeError("Gemini adapter received no usable message content.")

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
        },
    }
    if system_texts:
        payload["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_texts).strip()}]
        }
    if max_tokens is not None:
        payload["generationConfig"]["maxOutputTokens"] = max_tokens
    thinking_budget = gemini_thinking_budget(model)
    if thinking_budget is not None:
        payload["generationConfig"]["thinkingConfig"] = {
            "thinkingBudget": thinking_budget
        }
    return payload


def _gemini_endpoint(binding: ProviderBinding, model: str) -> str:
    base_url = (binding.base_url or GEMINI_DEFAULT_BASE_URL).rstrip("/")
    return f"{base_url}/models/{model}:generateContent"


def _gemini_extract_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        prompt_feedback = data.get("promptFeedback") or {}
        reason = (
            prompt_feedback.get("blockReason")
            or prompt_feedback.get("block_reason")
            or "no_candidates"
        )
        raise RuntimeError(f"Gemini returned no candidates: {reason}")

    candidate = candidates[0] or {}
    content = candidate.get("content") or {}
    parts = content.get("parts") or []
    chunks = [
        str(part.get("text") or "").strip()
        for part in parts
        if str(part.get("text") or "").strip()
    ]
    return "\n".join(chunks).strip()


def _chat_once_gemini(
    binding: ProviderBinding,
    messages: List[Dict[str, Any]],
    *,
    temperature: float,
    model: str,
    tools: Optional[List[Dict[str, Any]]],
    **extra_kwargs: Any,
):
    if tools:
        raise RuntimeError(
            "Gemini adapter does not yet support tool-enabled agent loops in this runtime."
        )
    if not binding.api_key:
        raise RuntimeError(
            f"API key is not configured for provider '{binding.provider}'"
        )

    payload = _messages_to_gemini_payload(
        messages,
        temperature=temperature,
        max_tokens=extra_kwargs.get("max_tokens"),
        model=model,
    )
    url = _gemini_endpoint(binding, model)
    headers = {
        "x-goog-api-key": binding.api_key,
        "Content-Type": "application/json",
    }
    last_exc: Exception | None = None
    for attempt in range(2):
        if attempt:
            time.sleep(3)
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            continue
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = ""
            try:
                detail = response.text[:1000]
            except Exception:
                detail = ""
            raise RuntimeError(
                f"Gemini request failed with status {response.status_code}: {detail or exc}"
            ) from exc
        data = response.json()
        return _response_with_content(_gemini_extract_text(data))
    raise requests.exceptions.Timeout(
        f"Gemini timed out after 2 attempts (model={model})"
    ) from last_exc


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
                        "recency_days": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_page",
                "description": "Завантажити сторінку за URL і повернути очищений текст.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                    },
                    "required": ["url"],
                },
            },
        },
    ]


def make_messages(
    system_prompt: str, context_msgs: List[Dict[str, Any]], user_msg: Any
) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(context_msgs)
    if user_msg:
        messages.append({"role": "user", "content": user_msg})
    return messages


def chat_once(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    use_reasoning: bool = False,
    model: Optional[str] = None,
    temperature: float = 0.3,
    capability: str = "chat_final",
    **extra_kwargs: Any,
):
    binding = _resolve_binding(capability, model_override=model)
    model_name = _pick_model(binding, use_reasoning, model_override=model)
    if is_gemini_native(binding):
        return _chat_once_gemini(
            binding,
            messages,
            temperature=temperature,
            model=model_name,
            tools=tools,
            **extra_kwargs,
        )

    kwargs = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if use_reasoning:
        kwargs.update(_maybe_reasoning_args(capability, use_reasoning))
    kwargs.update(extra_kwargs)
    return _get_client(binding).chat.completions.create(**kwargs)
