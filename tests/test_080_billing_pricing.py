"""Unit tests for billing.pricing — pure-computation only (no DB)."""
from __future__ import annotations

from decimal import Decimal

from billing.pricing import compute_cost_from_row


def test_pricing_known_row_uses_provider_rates():
    row = {
        "input_usd_per_1m": Decimal("1.00"),
        "output_usd_per_1m": Decimal("3.00"),
        "unit_usd": Decimal("0"),
        "markup_pct": Decimal("40"),
        "uah_per_usd": Decimal("40"),
    }
    breakdown = compute_cost_from_row(row, tokens_in=1_000_000, tokens_out=0)
    # 1.00 * 1M / 1M = 1.00 USD raw → 1.40 USD with 40% markup → 56 UAH
    assert breakdown.cost_usd == Decimal("1.400000")
    assert breakdown.cost_uah == Decimal("56.0000")
    assert breakdown.source == "pricing_table"


def test_pricing_combines_input_output_unit():
    row = {
        "input_usd_per_1m": Decimal("2.00"),
        "output_usd_per_1m": Decimal("6.00"),
        "unit_usd": Decimal("0.005"),
        "markup_pct": Decimal("0"),
        "uah_per_usd": Decimal("40"),
    }
    breakdown = compute_cost_from_row(
        row, tokens_in=500_000, tokens_out=100_000, unit_count=2
    )
    # 2 * 0.5 + 6 * 0.1 + 0.005 * 2 = 1.0 + 0.6 + 0.01 = 1.61 USD
    assert breakdown.cost_usd == Decimal("1.610000")
    assert breakdown.cost_uah == Decimal("64.4000")


def test_pricing_missing_row_uses_fallback():
    breakdown = compute_cost_from_row(None, tokens_in=1_000_000, tokens_out=0)
    # No input_rate/output_rate → cost is 0 even with markup applied
    assert breakdown.cost_usd == Decimal("0.000000")
    assert breakdown.cost_uah == Decimal("0.0000")
    assert breakdown.source == "fallback"


def test_pricing_zero_usage_yields_zero_cost():
    row = {
        "input_usd_per_1m": Decimal("100"),
        "output_usd_per_1m": Decimal("100"),
        "unit_usd": Decimal("100"),
        "markup_pct": Decimal("100"),
        "uah_per_usd": Decimal("100"),
    }
    breakdown = compute_cost_from_row(row, tokens_in=0, tokens_out=0, unit_count=0)
    assert breakdown.cost_uah == Decimal("0.0000")
