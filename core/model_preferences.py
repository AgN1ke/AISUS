from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelGroupDef:
    slug: str
    title: str
    description: str
    provider_setting_key: str
    model_setting_key: str
    capabilities: tuple[str, ...]
    providers: dict[str, tuple[str, ...]]


MODEL_GROUPS: tuple[ModelGroupDef, ...] = (
    ModelGroupDef(
        slug="chat",
        title="💬 Відповідь",
        description="Головна модель для фінальної відповіді користувачу.",
        provider_setting_key="chat_provider",
        model_setting_key="chat_model",
        capabilities=("chat_final",),
        providers={
            "openai": ("gpt-5.4-mini", "gpt-5.4", "gpt-4.1-mini", "o4-mini"),
            "anthropic": ("claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"),
            "gemini": ("gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"),
            "deepseek": ("deepseek-chat", "deepseek-reasoner"),
            "mistral": ("mistral-large-latest", "mistral-medium-latest"),
            "xai": ("grok-4", "grok-3"),
        },
    ),
    ModelGroupDef(
        slug="think",
        title="🧠 Думалка",
        description="Planner і стискання пам'яті. Дешевші моделі, не фінальний текст.",
        provider_setting_key="think_provider",
        model_setting_key="think_model",
        capabilities=("planner_reasoning", "memory_summary"),
        providers={
            "openai": ("gpt-5.4-nano", "gpt-5.4-mini", "gpt-4.1-nano", "gpt-4.1-mini"),
            "anthropic": ("claude-haiku-4-5", "claude-sonnet-4-6"),
            "gemini": ("gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3.1-pro-preview"),
            "deepseek": ("deepseek-chat", "deepseek-reasoner"),
            "mistral": ("mistral-small-latest", "mistral-medium-latest"),
            "xai": ("grok-3-mini", "grok-3"),
        },
    ),
    ModelGroupDef(
        slug="media",
        title="🎙 Медіа",
        description="Аналіз зображень і пов'язаного мультимодального контексту.",
        provider_setting_key="media_provider",
        model_setting_key="media_model",
        capabilities=("vision_image",),
        providers={
            "openai": ("gpt-5.4-mini", "gpt-4.1-mini", "gpt-4o"),
            "anthropic": ("claude-sonnet-4-6", "claude-opus-4-6"),
            "gemini": ("gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"),
        },
    ),
)

MODEL_GROUPS_BY_SLUG = {group.slug: group for group in MODEL_GROUPS}

_GROUP_BY_CAPABILITY: dict[str, ModelGroupDef] = {}
for _group in MODEL_GROUPS:
    for _capability in _group.capabilities:
        _GROUP_BY_CAPABILITY[_capability] = _group


def group_for_capability(capability: str) -> ModelGroupDef | None:
    return _GROUP_BY_CAPABILITY.get((capability or "").strip())


def group_by_slug(slug: str) -> ModelGroupDef | None:
    return MODEL_GROUPS_BY_SLUG.get((slug or "").strip())


def provider_models(group_slug: str, provider_slug: str) -> tuple[str, ...]:
    group = group_by_slug(group_slug)
    if not group:
        return tuple()
    return group.providers.get((provider_slug or "").strip().lower(), tuple())
