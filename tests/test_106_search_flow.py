from __future__ import annotations

import pytest

import agent.runner as runner


@pytest.mark.asyncio
async def test_run_search_converts_chat_final_bare_citation(monkeypatch):
    async def fake_direct_search(*_args, **_kwargs):
        return runner.SearchOutcome(
            status="ok",
            evidence_block="status: ok",
            queries=["погода Київ 2026-05-05"],
            citation_map={
                2: "https://sinoptik.ua/pohoda/kyiv/2026-05-05",
            },
        )

    async def fake_run_capability(*_args, **_kwargs):
        return "У Києві буде +14...+24 [2]."

    monkeypatch.setattr(runner, "_run_direct_search", fake_direct_search)
    monkeypatch.setattr(runner, "run_capability", fake_run_capability)

    out = await runner.run_search(123, "яка погода в києві буде у вівторок?")

    assert "[sinoptik.ua](https://sinoptik.ua/pohoda/kyiv/2026-05-05)" in out
    assert "[2]" not in out
