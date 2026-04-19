"""Seed or refresh the multitenant pricing table.

By default this inserts only missing rows so admin-customized pricing remains
untouched. Use ``--force`` to refresh the tracked defaults for all known rows.

Usage:
    python scripts/seed_pricing.py
    python scripts/seed_pricing.py --force
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from billing.pricing_seed import DEFAULT_PRICING_ROWS, seed_pricing_defaults
from db.connection import init_db
from db.migrate import apply_migrations


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed multitenant pricing rows.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Upsert tracked defaults even if a row already exists.",
    )
    return parser


async def main(force: bool = False) -> int:
    await init_db()
    await apply_migrations()

    markup_env = os.getenv("BILLING_DEFAULT_MARKUP_PCT")
    uah_env = os.getenv("BILLING_DEFAULT_UAH_PER_USD")
    markup = Decimal(markup_env) if markup_env else None
    rate = Decimal(uah_env) if uah_env else None

    changed = await seed_pricing_defaults(
        force=force,
        markup_pct=markup,
        uah_per_usd=rate,
    )
    skipped = len(DEFAULT_PRICING_ROWS) - changed
    mode = "upserted" if force else "inserted"
    print(f"{mode} {changed} pricing rows; skipped {skipped}.")
    return 0


if __name__ == "__main__":
    args = _build_parser().parse_args()
    raise SystemExit(asyncio.run(main(force=args.force)))
