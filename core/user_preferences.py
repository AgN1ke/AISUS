from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceOption:
    voice_id: str
    title: str
    description: str


@dataclass(frozen=True)
class PersonaPreset:
    slug: str
    title: str
    description: str
    prompt: str


VOICE_OPTIONS: tuple[VoiceOption, ...] = (
    VoiceOption("alloy", "Alloy", "Нейтральний універсальний голос."),
    VoiceOption("echo", "Echo", "Спокійний нижчий тембр."),
    VoiceOption("fable", "Fable", "М'якший і трохи тепліший голос."),
    VoiceOption("onyx", "Onyx", "Щільніший і стриманий голос."),
    VoiceOption("nova", "Nova", "Живіший і легший голос."),
    VoiceOption("shimmer", "Shimmer", "Найтепліший і м'якший із базових голосів."),
)

VOICE_OPTIONS_BY_ID = {item.voice_id: item for item in VOICE_OPTIONS}

PERSONA_PRESETS: tuple[PersonaPreset, ...] = (
    PersonaPreset(
        slug="default",
        title="Default",
        description="Без персонального оверрайду, тільки server persona.",
        prompt="",
    ),
    PersonaPreset(
        slug="sharp",
        title="Sharp",
        description="Пряміші й жорсткіші формулювання без зайвої м'якості.",
        prompt=(
            "Тримай тон прямим і зібраним. Не розмазуй відповідь, не підсолоджуй формулювання, "
            "якщо можна сказати коротше й точніше."
        ),
    ),
    PersonaPreset(
        slug="friendly",
        title="Friendly",
        description="М'якший і тепліший стиль без втрати конкретики.",
        prompt=(
            "Тримай тон людяним і м'яким. Пояснюй доброзичливо, але без води й без втрати точності."
        ),
    ),
    PersonaPreset(
        slug="technical",
        title="Technical",
        description="Акцент на інженерну точність, припущення й trade-offs.",
        prompt=(
            "Відповідай як прагматичний інженер: відділяй факти від припущень, явно називай "
            "обмеження, ризики й trade-offs."
        ),
    ),
    PersonaPreset(
        slug="concise",
        title="Concise",
        description="Максимально стислий стиль, тільки суть.",
        prompt=(
            "Тримай відповіді максимально стислими. Давай тільки суть і прибирай усе, що не рухає "
            "відповідь вперед."
        ),
    ),
)

PERSONA_PRESETS_BY_SLUG = {item.slug: item for item in PERSONA_PRESETS}


def voice_option(voice_id: str | None) -> VoiceOption | None:
    normalized = (voice_id or "").strip().lower()
    if not normalized:
        return None
    return VOICE_OPTIONS_BY_ID.get(normalized)


def persona_preset(slug: str | None) -> PersonaPreset | None:
    normalized = (slug or "").strip().lower()
    if not normalized:
        return None
    return PERSONA_PRESETS_BY_SLUG.get(normalized)

