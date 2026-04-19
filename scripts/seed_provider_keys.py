"""Seed provider API keys into the keypool.

Reads JSON from stdin: a list of {"provider", "raw_key", "label", "rpm_limit"?, "tpm_limit"?}.
Encrypts via billing.crypto and inserts via billing.keypool.register_key.

Usage:
    python scripts/seed_provider_keys.py < keys.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from billing.keypool import register_key
from db.connection import init_db
from db.migrate import apply_migrations


async def main() -> int:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, list):
        print("expected a JSON list", file=sys.stderr)
        return 2

    await init_db()
    await apply_migrations()

    inserted = 0
    for item in payload:
        kid = await register_key(
            provider=item["provider"],
            raw_key=item["raw_key"],
            label=item.get("label"),
            rpm_limit=item.get("rpm_limit"),
            tpm_limit=item.get("tpm_limit"),
        )
        print(f"  + {item['provider']:9s} {item.get('label') or '-':20s} key_id={kid}")
        inserted += 1

    print(f"seeded {inserted} keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
