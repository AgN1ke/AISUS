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


def openai_api_key() -> str:
    return env_first("OPENAI_API_KEY", "OPENAI_APIKEY", "OPENAI_API_KEY_V1", default="")


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


def reasoning_model() -> str:
    return env_first("OPENAI_REASONING_MODEL", default="")


def reasoning_effort() -> str:
    return env_first("REASONING_EFFORT", "OPENAI_REASONING_EFFORT", default="medium")


def chat_base_url() -> str | None:
    return env_url(
        "OPENAI_CHAT_BASE_URL",
        "OPENAI_BASE_URL",
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


def provider_supports_reasoning(provider_name: str) -> bool:
    normalized = env_slot(provider_name)
    return env_bool(
        f"PROVIDER_{normalized}_SUPPORTS_REASONING",
        default=True,
    )


def gemini_thinking_budget(model_name: str | None = None) -> int | None:
    raw = env_first(
        "PROVIDER_GEMINI_THINKING_BUDGET",
        "GEMINI_THINKING_BUDGET",
        default=None,
    )
    if raw not in (None, ""):
        try:
            return int(str(raw).strip())
        except Exception:
            return 0

    model = (model_name or "").strip().lower()
    if "gemini-2.5-flash" in model:
        return 0
    return None


def telegram_bot_token() -> str:
    return env_first("TG_BOT_TOKEN", "MYAPI_BOT_TOKEN", default="")


def chat_join_password() -> str:
    return env_first("CHAT_JOIN_PASSWORD", "PASSWORD", default="")
