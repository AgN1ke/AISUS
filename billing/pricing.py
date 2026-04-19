"""Pricing lookup and USD → UAH conversion with markup.

The `pricing` table holds per-(provider, model, kind) base rates plus our
markup and a snapshot of UAH/USD rate. `compute_cost_uah` uses these to
convert a token usage record into the UAH amount we debit from the user.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from db.connection import execute, fetchone

logger = logging.getLogger(__name__)

_VALID_KINDS = {"llm", "search", "tts", "stt", "other"}


def _default_markup_pct() -> Decimal:
    raw = os.getenv("BILLING_DEFAULT_MARKUP_PCT", "40")
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal("40")


def _default_uah_per_usd() -> Decimal:
    raw = os.getenv("BILLING_DEFAULT_UAH_PER_USD", "40")
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal("40")


@dataclass
class CostBreakdown:
    cost_usd: Decimal
    cost_uah: Decimal
    markup_pct: Decimal
    uah_per_usd: Decimal
    source: str  # "pricing_table" | "fallback"


def _quantize_usd(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _quantize_uah(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


async def get_pricing_row(
    provider: str,
    model: str,
    kind: str = "llm",
) -> Optional[dict]:
    return await fetchone(
        """
        SELECT * FROM pricing
        WHERE provider=%s AND model=%s AND kind=%s
        LIMIT 1
        """,
        (provider, model, kind),
    )


async def upsert_pricing(
    *,
    provider: str,
    model: str,
    kind: str = "llm",
    input_usd_per_1m: Decimal | float | int = 0,
    output_usd_per_1m: Decimal | float | int = 0,
    unit_usd: Decimal | float | int = 0,
    markup_pct: Decimal | float | int | None = None,
    uah_per_usd: Decimal | float | int | None = None,
) -> None:
    if kind not in _VALID_KINDS:
        raise ValueError(f"invalid pricing kind: {kind}")
    markup = Decimal(str(markup_pct)) if markup_pct is not None else _default_markup_pct()
    rate = Decimal(str(uah_per_usd)) if uah_per_usd is not None else _default_uah_per_usd()
    await execute(
        """
        INSERT INTO pricing
          (provider, model, kind, input_usd_per_1m, output_usd_per_1m,
           unit_usd, markup_pct, uah_per_usd)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          input_usd_per_1m = VALUES(input_usd_per_1m),
          output_usd_per_1m = VALUES(output_usd_per_1m),
          unit_usd = VALUES(unit_usd),
          markup_pct = VALUES(markup_pct),
          uah_per_usd = VALUES(uah_per_usd)
        """,
        (
            provider,
            model,
            kind,
            Decimal(str(input_usd_per_1m)),
            Decimal(str(output_usd_per_1m)),
            Decimal(str(unit_usd)),
            markup,
            rate,
        ),
    )


def compute_cost_from_row(
    row: dict | None,
    *,
    tokens_in: int,
    tokens_out: int,
    unit_count: int = 0,
) -> CostBreakdown:
    """Pure computation. Separated for deterministic testing (no DB)."""
    if row:
        input_rate = Decimal(str(row.get("input_usd_per_1m") or 0))
        output_rate = Decimal(str(row.get("output_usd_per_1m") or 0))
        unit_rate = Decimal(str(row.get("unit_usd") or 0))
        markup = Decimal(str(row.get("markup_pct") or 0))
        uah_rate = Decimal(str(row.get("uah_per_usd") or 0))
        source = "pricing_table"
    else:
        input_rate = Decimal("0")
        output_rate = Decimal("0")
        unit_rate = Decimal("0")
        markup = _default_markup_pct()
        uah_rate = _default_uah_per_usd()
        source = "fallback"

    raw_usd = (
        input_rate * Decimal(int(tokens_in)) / Decimal("1000000")
        + output_rate * Decimal(int(tokens_out)) / Decimal("1000000")
        + unit_rate * Decimal(int(unit_count))
    )
    marked_usd = raw_usd * (Decimal("1") + markup / Decimal("100"))
    cost_uah = marked_usd * uah_rate

    return CostBreakdown(
        cost_usd=_quantize_usd(marked_usd),
        cost_uah=_quantize_uah(cost_uah),
        markup_pct=markup,
        uah_per_usd=uah_rate,
        source=source,
    )


async def compute_cost_uah(
    *,
    provider: str,
    model: str,
    kind: str = "llm",
    tokens_in: int = 0,
    tokens_out: int = 0,
    unit_count: int = 0,
) -> CostBreakdown:
    row = await get_pricing_row(provider, model, kind)
    breakdown = compute_cost_from_row(
        row,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        unit_count=unit_count,
    )
    if breakdown.source == "fallback":
        logger.warning(
            "pricing.miss provider=%s model=%s kind=%s — using fallback markup=%s rate=%s",
            provider,
            model,
            kind,
            breakdown.markup_pct,
            breakdown.uah_per_usd,
        )
    return breakdown
