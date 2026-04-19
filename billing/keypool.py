"""Service layer over db/keypool_repository.

Responsibilities:
- Decrypt provider keys before handing them to the LLM client.
- Track successful use (last_used_at, total_requests, total_spent_usd).
- React to rate limits and auth errors by cooldown/disable.

Stage 2 scaffold: import-safe, integration wiring for agent/llm.py lands in
Stage 3. Seed via `billing.keypool.register_key(...)`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from db import keypool_repository as repo

from .crypto import decrypt_key, encrypt_key

logger = logging.getLogger(__name__)


@dataclass
class AcquiredKey:
    key_id: int
    provider: str
    api_key: str
    label: str | None


async def register_key(
    *,
    provider: str,
    raw_key: str,
    label: str | None = None,
    rpm_limit: int | None = None,
    tpm_limit: int | None = None,
) -> int:
    """Encrypt + insert (or refresh) a provider key. Returns key_id."""
    if not raw_key:
        raise ValueError("raw_key is empty")
    ciphertext = encrypt_key(raw_key)
    key_id = await repo.add_provider_key(
        provider=provider,
        encrypted_key=ciphertext,
        raw_key_for_hash=raw_key,
        label=label,
        rpm_limit=rpm_limit,
        tpm_limit=tpm_limit,
    )
    logger.info("keypool.register provider=%s key_id=%s label=%s", provider, key_id, label)
    return key_id


async def acquire(provider: str) -> Optional[AcquiredKey]:
    await repo.clear_cooldowns()
    row = await repo.pick_available_key(provider)
    if not row:
        return None
    try:
        plaintext = decrypt_key(str(row["encrypted_key"]))
    except Exception as exc:
        logger.error("keypool.decrypt_failed key_id=%s: %s", row.get("id"), exc)
        await repo.mark_key_error(int(row["id"]), f"decrypt_failed: {exc}", disable=True)
        return None
    return AcquiredKey(
        key_id=int(row["id"]),
        provider=provider,
        api_key=plaintext,
        label=row.get("label"),
    )


async def record_success(key_id: int, *, cost_usd: Decimal | float | int = 0) -> None:
    await repo.mark_key_used(key_id, cost_usd=cost_usd)


async def record_rate_limit(key_id: int, cooldown_seconds: int = 60) -> None:
    logger.warning("keypool.rate_limited key_id=%s cooldown=%ss", key_id, cooldown_seconds)
    await repo.mark_key_rate_limited(key_id, cooldown_seconds=cooldown_seconds)


async def record_error(key_id: int, error_text: str, *, disable: bool = False) -> None:
    logger.warning("keypool.error key_id=%s disable=%s text=%s", key_id, disable, error_text[:200])
    await repo.mark_key_error(key_id, error_text, disable=disable)


async def reset_cooldowns() -> int:
    return await repo.clear_cooldowns()
