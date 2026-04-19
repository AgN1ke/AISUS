"""Verify _maybe_emit_billing fires for planner_reasoning (sync chat_once in thread)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.llm import set_main_event_loop
from agent.planner import _validate_search, PlannerInput
from billing.bootstrap import begin_turn
from billing.runtime import use_billing_context
from db.connection import init_db, fetchall


async def main() -> int:
    await init_db()
    set_main_event_loop(asyncio.get_running_loop())

    before = await fetchall(
        "SELECT COUNT(*) AS c FROM transactions WHERE capability='planner_reasoning'"
    )
    n_before = before[0]["c"]
    print(f"planner_reasoning txns before: {n_before}")

    ctx = await begin_turn(
        chat_id=311422683,
        user_id=311422683,
        tg_chat_type="private",
        tg_username="AgNike",
        first_name="test",
        tg_message_id=88888,
        user_message_text="яка погода в Києві сьогодні",
    )
    assert ctx is not None and ctx.is_complete()

    task = PlannerInput(
        user_text="яка погода в Києві сьогодні",
        dialogue_context=[],
    )

    # _validate_search runs sync chat_once inside a thread (mimics planner real path).
    async with use_billing_context(ctx):
        await asyncio.to_thread(_validate_search, task)

    # Threadsafe future needs a beat to land.
    await asyncio.sleep(2.0)

    after = await fetchall(
        "SELECT id, capability, provider, model, key_id, status, cost_uah "
        "FROM transactions WHERE capability='planner_reasoning' ORDER BY id DESC LIMIT 3"
    )
    print(f"planner_reasoning txns after: {len(after)}")
    for t in after:
        print(f"  #{t['id']:>3} {t['capability']} {t['provider']} {t['model']} key={t['key_id']} uah={t['cost_uah']} {t['status']}")

    ok = len(after) > n_before
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
