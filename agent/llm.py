from __future__ import annotations

import asyncio
import logging
import re
import time
from functools import lru_cache
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI

from core.env import (
    GEMINI_DEFAULT_BASE_URL,
    can_reason,
    capability_reasoning_effort,
    capability_reasoning_enabled,
    gemini_thinking_level,
    gemini_thinking_budget,
)
from core.provider_registry import (
    ProviderBinding,
    is_gemini_native,
    is_openai_compatible,
    resolve_provider_binding,
)

logger = logging.getLogger(__name__)


_MAIN_LOOP: "asyncio.AbstractEventLoop | None" = None


def set_main_event_loop(loop: "asyncio.AbstractEventLoop | None") -> None:
    """Capture the runtime event loop so sync callsites can schedule logging."""
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def _maybe_emit_billing(
    *,
    response: Any,
    capability: str,
    binding: ProviderBinding,
    model_name: str,
    started_at: float,
    status: str = "success",
    error_text: str | None = None,
) -> None:
    """Schedule a transactions row write if a BillingContext is active.

    Fire-and-forget. Works from both the event loop thread and worker threads
    (planner/search_task are dispatched via asyncio.to_thread). The latter rely
    on the main loop captured at runtime boot via set_main_event_loop().
    """
    try:
        from billing.runtime import current_billing_context
        from billing.gateway import log_llm_transaction
    except Exception:
        return

    ctx = current_billing_context()
    if ctx is None or not ctx.is_complete():
        return

    latency_ms = int((time.monotonic() - started_at) * 1000)
    coro = log_llm_transaction(
        response,
        billing_context=ctx,
        capability=capability,
        provider=binding.provider,
        model=model_name,
        key_id=binding.key_id,
        latency_ms=latency_ms,
        status=status,
        error_text=error_text,
    )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop is not None:
            task = loop.create_task(coro)
            task.add_done_callback(_billing_task_done)
        elif _MAIN_LOOP is not None and not _MAIN_LOOP.is_closed():
            fut = asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)
            fut.add_done_callback(_billing_future_done)
        else:
            coro.close()
            logger.debug("llm.billing_no_loop_available")
    except Exception as exc:
        logger.debug("llm.billing_schedule_failed: %s", exc)


def _billing_future_done(fut: "asyncio.futures.Future[Any]") -> None:
    try:
        exc = fut.exception()
    except Exception:
        return
    if exc is not None:
        logger.warning("llm.billing_log_error: %s", exc)


def _billing_task_done(task: "asyncio.Task[Any]") -> None:
    try:
        exc = task.exception()
    except (asyncio.CancelledError, asyncio.InvalidStateError):
        return
    if exc is not None:
        logger.warning("llm.billing_log_error: %s", exc)

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


def _normalize_reasoning_effort(provider: str, model: str, effort: str) -> str:
    raw = (effort or "").strip().lower()
    if raw not in {"none", "low", "medium", "high", "xhigh"}:
        raw = "medium"
    provider_name = (provider or "").strip().lower()
    model_name = (model or "").strip().lower()
    if provider_name in {"openai", "openrouter"} and any(
        tag in model_name for tag in ("o1", "o3", "o4")
    ):
        if raw == "none":
            return "low"
        if raw == "xhigh":
            return "high"
    return raw


def _reasoning_active(
    binding: ProviderBinding,
    model_name: str,
    use_reasoning: bool,
) -> bool:
    if not use_reasoning:
        return False
    if not capability_reasoning_enabled(binding.capability):
        return False
    provider_name = (binding.provider or "").strip().lower()
    if provider_name == "deepseek":
        return "reasoner" in (model_name or "").strip().lower()
    return can_reason(provider_name, model_name)


def _maybe_reasoning_args(
    binding: ProviderBinding,
    model_name: str,
    use_reasoning: bool,
) -> dict:
    if not _reasoning_active(binding, model_name, use_reasoning):
        return {}
    effort = _normalize_reasoning_effort(
        binding.provider,
        model_name,
        capability_reasoning_effort(binding.capability),
    )
    provider_name = (binding.provider or "").strip().lower()
    if provider_name == "openrouter":
        if "reasoner" in (model_name or "").strip().lower():
            return {}
        return {"extra_body": {"reasoning": {"effort": effort}}}
    if provider_name != "openai":
        return {}
    return {"reasoning": {"effort": effort}}


def _pick_model(
    binding: ProviderBinding,
    reasoning: bool,
    model_override: Optional[str] = None,
) -> str:
    del model_override
    model_name = binding.model
    if not reasoning or not capability_reasoning_enabled(binding.capability):
        return model_name
    if (
        (binding.provider or "").strip().lower() == "deepseek"
        and "reasoner" not in (model_name or "").strip().lower()
    ):
        return "deepseek-reasoner"
    return model_name


def _response_with_content(text: str, usage: SimpleNamespace | None = None):
    message = SimpleNamespace(content=text, tool_calls=None)
    choice = SimpleNamespace(message=message)
    response = SimpleNamespace(choices=[choice])
    if usage is not None:
        response.usage = usage
    return response


def _gemini_usage(data: dict[str, Any]) -> SimpleNamespace | None:
    meta = data.get("usageMetadata") or data.get("usage_metadata")
    if not isinstance(meta, dict):
        return None
    prompt = int(meta.get("promptTokenCount") or meta.get("prompt_token_count") or 0)
    candidate_tokens = int(
        meta.get("candidatesTokenCount") or meta.get("candidates_token_count") or 0
    )
    thought_tokens = int(
        meta.get("thoughtsTokenCount") or meta.get("thoughts_token_count") or 0
    )
    total = int(meta.get("totalTokenCount") or meta.get("total_token_count") or 0)
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=candidate_tokens + thought_tokens,
        candidates_tokens=candidate_tokens,
        thoughts_tokens=thought_tokens,
        total_tokens=total or (prompt + candidate_tokens + thought_tokens),
    )


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
    reasoning_active: bool,
    capability: str,
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
    thinking_level = gemini_thinking_level(
        model,
        reasoning_active=reasoning_active,
        capability=capability,
    )
    if thinking_level is not None:
        payload["generationConfig"]["thinkingConfig"] = {
            "thinkingLevel": thinking_level
        }
    thinking_budget = gemini_thinking_budget(
        model,
        reasoning_active=reasoning_active,
        capability=capability,
    )
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
    reasoning_active: bool,
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
        reasoning_active=reasoning_active,
        capability=binding.capability,
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
        return _response_with_content(_gemini_extract_text(data), usage=_gemini_usage(data))
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
    reasoning_active = _reasoning_active(binding, model_name, use_reasoning)
    started_at = time.monotonic()
    try:
        response = _dispatch_chat_once(
            binding=binding,
            model_name=model_name,
            messages=messages,
            tools=tools,
            reasoning_active=reasoning_active,
            temperature=temperature,
            extra_kwargs=extra_kwargs,
        )
    except Exception as exc:
        _maybe_emit_billing(
            response=None,
            capability=capability,
            binding=binding,
            model_name=model_name,
            started_at=started_at,
            status="failed",
            error_text=str(exc)[:500],
        )
        raise
    _maybe_emit_billing(
        response=response,
        capability=capability,
        binding=binding,
        model_name=model_name,
        started_at=started_at,
    )
    return response


def _dispatch_chat_once(
    *,
    binding: ProviderBinding,
    model_name: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    reasoning_active: bool,
    temperature: float,
    extra_kwargs: Dict[str, Any],
):
    if is_gemini_native(binding):
        return _chat_once_gemini(
            binding,
            messages,
            temperature=temperature,
            model=model_name,
            tools=tools,
            reasoning_active=reasoning_active,
            **extra_kwargs,
        )

    reasoning_args = _maybe_reasoning_args(binding, model_name, reasoning_active)
    provider_name = (binding.provider or "").strip().lower()
    lowered_model = (model_name or "").strip().lower()
    is_openai_reasoning_model = provider_name in {"openai", "openrouter"} and (
        "gpt-5" in lowered_model or any(tag in lowered_model for tag in ("o1", "o3", "o4"))
    )
    is_deepseek_reasoner = "reasoner" in lowered_model

    kwargs = {
        "model": model_name,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    max_tokens = extra_kwargs.pop("max_tokens", None)
    extra_body = extra_kwargs.pop("extra_body", None)
    if reasoning_args or is_deepseek_reasoner:
        if extra_body and "extra_body" in reasoning_args:
            merged_extra_body = dict(extra_body)
            merged_extra_body.update(reasoning_args["extra_body"])
            kwargs["extra_body"] = merged_extra_body
        elif extra_body:
            kwargs["extra_body"] = extra_body
        kwargs.update({k: v for k, v in reasoning_args.items() if k != "extra_body"})
        if is_openai_reasoning_model and max_tokens is not None:
            kwargs["max_completion_tokens"] = max_tokens
        elif max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
    else:
        kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if extra_body:
            kwargs["extra_body"] = extra_body

    if not reasoning_args and not is_deepseek_reasoner:
        kwargs.setdefault("temperature", temperature)
    elif not is_openai_reasoning_model and not is_deepseek_reasoner and "temperature" not in kwargs:
        kwargs["temperature"] = temperature

    kwargs.update(extra_kwargs)
    return _get_client(binding).chat.completions.create(**kwargs)
