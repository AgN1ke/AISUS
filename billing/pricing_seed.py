"""Canonical default pricing rows for multitenant billing.

This module keeps one current snapshot of provider rates used to seed the
`pricing` table. The runtime should not depend on a manual script to populate
pricing: missing rows are inserted automatically during DB bootstrap, while
manual admin edits stay intact because the default seeding path only inserts
missing rows.

The numbers below are a pragmatic production snapshot for April 2026. They use
the standard realtime API rates for the specific model aliases exposed in the
project's current model catalog. Where a vendor documents pricing at the model
family level (for example Claude Sonnet 4 vs Claude Sonnet 4.6), we map the
project alias to the corresponding documented family rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from billing.pricing import get_pricing_row, upsert_pricing


@dataclass(frozen=True)
class PricingSeedRow:
    provider: str
    model: str
    kind: str = "llm"
    input_usd_per_1m: str = "0"
    output_usd_per_1m: str = "0"
    unit_usd: str = "0"


DEFAULT_PRICING_ROWS: tuple[PricingSeedRow, ...] = (
    # OpenAI standard pricing, April 2026 snapshot.
    PricingSeedRow("openai", "gpt-5.4-mini", "llm", "0.75", "4.50"),
    PricingSeedRow("openai", "gpt-5.4", "llm", "2.50", "15.00"),
    PricingSeedRow("openai", "gpt-5.4-nano", "llm", "0.20", "1.25"),
    PricingSeedRow("openai", "gpt-4.1-mini", "llm", "0.40", "1.60"),
    PricingSeedRow("openai", "gpt-4.1-nano", "llm", "0.10", "0.40"),
    PricingSeedRow("openai", "gpt-4o", "llm", "2.50", "10.00"),
    PricingSeedRow("openai", "o4-mini", "llm", "1.10", "4.40"),
    # Gemini Developer API standard pricing. For tiered long-context models we
    # use the standard <=200k prompt tier because the current schema stores one
    # rate per model, not a piecewise schedule.
    PricingSeedRow("gemini", "gemini-3.1-pro-preview", "llm", "2.00", "12.00"),
    PricingSeedRow("gemini", "gemini-2.5-pro", "llm", "2.25", "18.00"),
    PricingSeedRow("gemini", "gemini-2.5-flash", "llm", "0.30", "2.50"),
    PricingSeedRow("gemini", "gemini-2.5-flash-lite", "llm", "0.10", "0.40"),
    # Anthropic family pricing mapped to project aliases.
    PricingSeedRow("anthropic", "claude-opus-4-6", "llm", "5.00", "25.00"),
    PricingSeedRow("anthropic", "claude-sonnet-4-6", "llm", "3.00", "15.00"),
    PricingSeedRow("anthropic", "claude-haiku-4-5", "llm", "1.00", "5.00"),
    # DeepSeek official API pricing.
    PricingSeedRow("deepseek", "deepseek-chat", "llm", "0.27", "1.10"),
    PricingSeedRow("deepseek", "deepseek-reasoner", "llm", "0.55", "2.19"),
    # Mistral latest aliases mapped to current latest model family list prices.
    PricingSeedRow("mistral", "mistral-large-latest", "llm", "0.50", "1.50"),
    PricingSeedRow("mistral", "mistral-medium-latest", "llm", "0.40", "2.00"),
    PricingSeedRow("mistral", "mistral-small-latest", "llm", "0.15", "0.60"),
    # xAI latest aliases mapped to current list pricing.
    PricingSeedRow("xai", "grok-4", "llm", "3.00", "15.00"),
    PricingSeedRow("xai", "grok-3", "llm", "3.00", "15.00"),
    PricingSeedRow("xai", "grok-3-mini", "llm", "0.30", "0.50"),
    # Audio / speech.
    PricingSeedRow("openai", "whisper-1", "stt", unit_usd="0.006"),
    PricingSeedRow("openai", "tts-1", "tts", input_usd_per_1m="15.00"),
    PricingSeedRow("openai", "tts-1-hd", "tts", input_usd_per_1m="30.00"),
    # Search providers.
    PricingSeedRow("brave", "brave-search", "search", unit_usd="0.005"),
    PricingSeedRow("tavily", "tavily-search", "search", unit_usd="0.008"),
)


async def seed_pricing_defaults(
    *,
    force: bool = False,
    markup_pct: Decimal | float | int | None = None,
    uah_per_usd: Decimal | float | int | None = None,
    rows: Sequence[PricingSeedRow] | None = None,
) -> int:
    """Insert default pricing rows.

    By default this is conservative: existing rows are left untouched so manual
    admin edits remain authoritative. `force=True` turns it into an upsert pass.
    Returns the number of rows inserted or upserted in this invocation.
    """
    changed = 0
    rowset: Iterable[PricingSeedRow] = rows or DEFAULT_PRICING_ROWS
    for row in rowset:
        existing = await get_pricing_row(row.provider, row.model, row.kind)
        if existing and not force:
            continue
        await upsert_pricing(
            provider=row.provider,
            model=row.model,
            kind=row.kind,
            input_usd_per_1m=row.input_usd_per_1m,
            output_usd_per_1m=row.output_usd_per_1m,
            unit_usd=row.unit_usd,
            markup_pct=markup_pct,
            uah_per_usd=uah_per_usd,
        )
        changed += 1
    return changed
