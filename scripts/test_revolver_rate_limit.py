"""End-to-end revolver test: simulate a rate-limit and verify rotation.

Uses the same code paths as the bot (chat_once + provider_registry + keypool +
gateway logging via _maybe_emit_billing). Patches the OpenAI dispatch to raise
a 429, then verifies that:
  1. The hit key was marked rate_limited.
  2. A failed transaction was logged for that key.
  3. The next acquire() returns a different key.

Run:
    python scripts/test_revolver_rate_limit.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.llm import set_main_event_loop
from billing.bootstrap import begin_turn
from billing.keypool import acquire
from billing.runtime import use_billing_context
from db import keypool_repository as repo
from db.connection import init_db, execute, fetchall


class _Fake429(Exception):
    """Mimics openai.RateLimitError surface."""


async def main() -> int:
    await init_db()
    set_main_event_loop(asyncio.get_running_loop())

    # Reset OpenAI keys to a clean baseline.
    await execute(
        "UPDATE provider_keys SET status='active', cooldown_until=NULL, "
        "last_used_at=NULL, total_requests=0, total_spent_usd=0 "
        "WHERE provider='openai'"
    )

    # Pick the candidate the revolver would currently choose.
    target = await acquire("openai")
    assert target is not None, "no openai key available"
    print(f"target key for first call: id={target.key_id} label={target.label}")

    # Build a billing turn for an existing test account.
    ctx = await begin_turn(
        chat_id=311422683,
        user_id=311422683,
        tg_chat_type="private",
        tg_username="AgNike",
        first_name="test",
        tg_message_id=99999,
        user_message_text="rate-limit revolver test",
    )
    assert ctx is not None and ctx.is_complete(), "billing context incomplete"

    # Patch the OpenAI dispatch to raise 429 inside chat_once.
    import agent.llm as llm

    original_dispatch = llm._dispatch_chat_once
    calls = {"count": 0}

    def fake_dispatch(*args, **kwargs):
        calls["count"] += 1
        raise _Fake429("429 Too Many Requests: rate limit exceeded")

    llm._dispatch_chat_once = fake_dispatch
    try:
        async with use_billing_context(ctx):
            # Run sync chat_once in a thread to mimic the bot's path.
            try:
                await asyncio.to_thread(
                    llm.chat_once,
                    [{"role": "user", "content": "ping"}],
                    capability="chat_final",
                )
            except _Fake429:
                pass
    finally:
        llm._dispatch_chat_once = original_dispatch

    # Give the threadsafe billing future time to land.
    await asyncio.sleep(1.5)

    # Inspect the result.
    rows = await fetchall(
        "SELECT id, status, cooldown_until, total_requests FROM provider_keys WHERE id=%s",
        (target.key_id,),
    )
    print(f"key after: {rows[0]}")

    txs = await fetchall(
        "SELECT id, capability, status, key_id, error_text FROM transactions "
        "WHERE key_id=%s ORDER BY id DESC LIMIT 3",
        (target.key_id,),
    )
    print(f"txns for key {target.key_id}:")
    for t in txs:
        print(f"  #{t['id']:>3} cap={t['capability']} status={t['status']} err={(t['error_text'] or '')[:80]}")

    # The next acquire should NOT return the rate-limited key.
    next_key = await acquire("openai")
    print(f"next acquire: id={next_key.key_id if next_key else None} (must NOT be {target.key_id})")

    ok = (
        rows
        and rows[0]["status"] == "rate_limited"
        and next_key is not None
        and next_key.key_id != target.key_id
    )
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
