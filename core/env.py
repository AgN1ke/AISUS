from __future__ import annotations

import os
import re
from typing import Any

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def env_slot(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_").upper()


def env_first(*names: str, default: Any = None) -> Any:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def env_url(*names: str, default: str | None = None) -> str | None:
    raw = env_first(*names, default=None)
    if raw is None:
        return default
    value = str(raw).strip().strip('"').strip("'")
    return value or default


def env_bool(*names: str, default: bool = False) -> bool:
    raw = env_first(*names, default=None)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def env_int(*names: str, default: int) -> int:
    raw = env_first(*names, default=None)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def db_pool_size() -> int:
    return max(1, env_int("DB_POOL_SIZE", default=50))


def llm_thread_pool_size() -> int:
    return max(1, env_int("LLM_THREAD_POOL_SIZE", default=128))


def openai_api_key() -> str:
    return env_first("OPENAI_API_KEY", "OPENAI_APIKEY", "OPENAI_API_KEY_V1", default="")


def openai_stt_api_key() -> str:
    return env_first(
        "OPENAI_STT_API_KEY",
        "OPENAI_AUDIO_API_KEY",
        "OPENAI_API_KEY",
        default="",
    )


def openai_tts_api_key() -> str:
    return env_first(
        "OPENAI_TTS_API_KEY",
        "OPENAI_AUDIO_API_KEY",
        "OPENAI_API_KEY",
        default="",
    )


def default_llm_provider() -> str:
    return (
        str(env_first("DEFAULT_LLM_PROVIDER", "LLM_PROVIDER", default="openai"))
        .strip()
        .lower()
    )


def chat_model() -> str:
    return env_first("OPENAI_CHAT_MODEL", "OPENAI_GPT_MODEL", default="gpt-4o-mini")


def planner_model() -> str:
    return env_first(
        "OPENAI_PLANNER_MODEL",
        "OPENAI_ROUTER_MODEL",
        "OPENAI_CHAT_MODEL",
        "OPENAI_GPT_MODEL",
        default="gpt-4o-mini",
    )


def capability_model(capability_name: str) -> str:
    normalized = env_slot(capability_name)
    if normalized == "PLANNER_REASONING":
        return env_first(f"CAPABILITY_{normalized}_MODEL", default=planner_model())
    if normalized == "MEMORY_SUMMARY":
        return env_first(
            f"CAPABILITY_{normalized}_MODEL",
            "OPENAI_SUMMARIZER_MODEL",
            default=chat_model(),
        )
    if normalized == "VISION_IMAGE":
        return env_first(
            f"CAPABILITY_{normalized}_MODEL",
            "OPENAI_VISION_MODEL",
            "VISION_MODEL",
            default=chat_model(),
        )
    if normalized:
        return env_first(f"CAPABILITY_{normalized}_MODEL", default=chat_model())
    return chat_model()


def capability_provider(capability_name: str) -> str:
    normalized = env_slot(capability_name)
    if normalized:
        return (
            str(
                env_first(
                    f"CAPABILITY_{normalized}_PROVIDER",
                    default=default_llm_provider(),
                )
            )
            .strip()
            .lower()
        )
    return default_llm_provider()


def capability_adapter(capability_name: str, default: str = "openai_chat") -> str:
    normalized = env_slot(capability_name)
    if normalized:
        return (
            str(env_first(f"CAPABILITY_{normalized}_ADAPTER", default=default))
            .strip()
            .lower()
        )
    return default


def can_reason(provider: str, model: str) -> bool:
    """Return True when this provider/model pair supports configurable reasoning."""
    p = (provider or "").strip().lower()
    m = (model or "").strip().lower()
    if not p or not m:
        return False
    if p == "openai":
        return "gpt-5" in m or any(tag in m for tag in ("o1", "o3", "o4"))
    if p == "gemini":
        return "gemini-2.5" in m or "gemini-3" in m
    if p == "deepseek":
        return "reasoner" in m
    if p == "openrouter":
        return (
            "gpt-5" in m
            or any(tag in m for tag in ("o1", "o3", "o4"))
            or "gemini-2.5" in m
            or "gemini-3" in m
            or "reasoner" in m
            or "claude-opus-4" in m
            or "claude-sonnet-4" in m
        )
    return False


def capability_reasoning_enabled(capability: str) -> bool:
    cap = env_slot(capability)
    if not cap:
        return False
    return env_bool(f"CAPABILITY_{cap}_REASONING_ENABLED", default=False)


def capability_reasoning_effort(capability: str) -> str:
    cap = env_slot(capability)
    if not cap:
        return "medium"
    raw = str(
        env_first(
            f"CAPABILITY_{cap}_REASONING_EFFORT",
            default="medium",
        )
    ).strip().lower()
    if raw in {"none", "low", "medium", "high", "xhigh"}:
        return raw
    return "medium"


def whisper_model() -> str:
    return env_first("OPENAI_WHISPER_MODEL", default="whisper-1")


def tts_model() -> str:
    return env_first("OPENAI_TTS_MODEL", default="gpt-4o-mini-tts")


def vocalizer_voice() -> str:
    return env_first("OPENAI_VOCALIZER_VOICE", default="alloy")


def chat_base_url() -> str | None:
    return env_url(
        "OPENAI_CHAT_BASE_URL",
        "OPENAI_BASE_URL",
        default=OPENAI_DEFAULT_BASE_URL,
    )


def stt_base_url() -> str | None:
    return env_url(
        "OPENAI_STT_BASE_URL",
        "OPENAI_AUDIO_BASE_URL",
        default=OPENAI_DEFAULT_BASE_URL,
    )


def tts_base_url() -> str | None:
    return env_url(
        "OPENAI_TTS_BASE_URL",
        "OPENAI_AUDIO_BASE_URL",
        default=OPENAI_DEFAULT_BASE_URL,
    )


def summarizer_base_url() -> str | None:
    return env_url("OPENAI_SUMMARIZER_BASE_URL", default=chat_base_url())


def vision_base_url() -> str | None:
    return env_url("OPENAI_VISION_BASE_URL", default=chat_base_url())


def provider_api_key(provider_name: str) -> str:
    normalized = env_slot(provider_name)
    names = [f"PROVIDER_{normalized}_API_KEY", f"{normalized}_API_KEY"]
    if normalized == "OPENAI":
        names.extend(["OPENAI_API_KEY", "OPENAI_APIKEY", "OPENAI_API_KEY_V1"])
    if normalized == "GEMINI":
        names.append("GEMINI_API_KEY")
    return env_first(*names, default="")


def provider_base_url(provider_name: str) -> str | None:
    normalized = env_slot(provider_name)
    names = [f"PROVIDER_{normalized}_BASE_URL", f"{normalized}_BASE_URL"]
    if normalized == "OPENAI":
        names.extend(["OPENAI_CHAT_BASE_URL", "OPENAI_BASE_URL"])
        return env_url(*names, default=OPENAI_DEFAULT_BASE_URL)
    if normalized == "GEMINI":
        return env_url(*names, default=GEMINI_DEFAULT_BASE_URL)
    return env_url(*names, default=None)


def gemini_thinking_level(
    model_name: str | None = None,
    *,
    reasoning_active: bool = False,
    capability: str | None = None,
) -> str | None:
    model = (model_name or "").strip().lower()
    if "gemini-3" not in model:
        return None

    if not reasoning_active:
        return None

    raw = env_first(
        "PROVIDER_GEMINI_THINKING_LEVEL",
        "GEMINI_THINKING_LEVEL",
        default=None,
    )
    if raw not in (None, ""):
        value = str(raw).strip().lower()
        if value in {"minimal", "low", "medium", "high"}:
            return value

    effort = capability_reasoning_effort(capability or "")
    mapping = {
        "none": "low",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "xhigh": "high",
    }
    return mapping.get(effort, "medium")


def gemini_thinking_budget(
    model_name: str | None = None,
    *,
    reasoning_active: bool = False,
    capability: str | None = None,
) -> int | None:
    raw = env_first(
        "PROVIDER_GEMINI_THINKING_BUDGET",
        "GEMINI_THINKING_BUDGET",
        default=None,
    )
    model = (model_name or "").strip().lower()
    if "gemini-2.5" not in model:
        return None

    if not reasoning_active:
        if "flash" in model:
            return 0
        return 128

    if raw not in (None, ""):
        try:
            parsed = int(str(raw).strip())
            if "flash" in model:
                if parsed <= 0:
                    return 0
                return max(128, min(parsed, 24576))
            return max(128, min(parsed, 32768))
        except Exception:
            if "flash" in model:
                return 0
            return 128

    effort = capability_reasoning_effort(capability or "")
    if "flash" in model:
        mapping = {
            "none": 0,
            "low": 1024,
            "medium": 8192,
            "high": 24576,
            "xhigh": 24576,
        }
        return mapping.get(effort, 8192)

    mapping = {
        "none": 128,
        "low": 1024,
        "medium": 8192,
        "high": 24576,
        "xhigh": 32768,
    }
    return mapping.get(effort, 8192)


def telegram_bot_token() -> str:
    return env_first("TG_BOT_TOKEN", "MYAPI_BOT_TOKEN", default="")


def chat_join_password() -> str:
    return env_first("CHAT_JOIN_PASSWORD", "PASSWORD", default="")
