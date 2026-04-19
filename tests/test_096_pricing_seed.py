from __future__ import annotations

from decimal import Decimal

import pytest

from billing.pricing_seed import PricingSeedRow, seed_pricing_defaults


@pytest.mark.asyncio
async def test_seed_pricing_defaults_inserts_only_missing(monkeypatch):
    rows = (
        PricingSeedRow("openai", "gpt-5.4-mini", "llm", "0.75", "4.50"),
        PricingSeedRow("gemini", "gemini-2.5-flash", "llm", "0.30", "2.50"),
    )
    existing = {
        ("openai", "gpt-5.4-mini", "llm"): {"provider": "openai"},
        ("gemini", "gemini-2.5-flash", "llm"): None,
    }
    upserts: list[dict] = []

    async def fake_get_pricing_row(provider, model, kind):
        return existing[(provider, model, kind)]

    async def fake_upsert_pricing(**kwargs):
        upserts.append(kwargs)

    monkeypatch.setattr("billing.pricing_seed.get_pricing_row", fake_get_pricing_row)
    monkeypatch.setattr("billing.pricing_seed.upsert_pricing", fake_upsert_pricing)

    changed = await seed_pricing_defaults(rows=rows)

    assert changed == 1
    assert len(upserts) == 1
    assert upserts[0]["provider"] == "gemini"
    assert upserts[0]["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_seed_pricing_defaults_force_upserts_existing(monkeypatch):
    rows = (
        PricingSeedRow("openai", "gpt-5.4-mini", "llm", "0.75", "4.50"),
        PricingSeedRow("gemini", "gemini-2.5-flash", "llm", "0.30", "2.50"),
    )
    upserts: list[dict] = []

    async def fake_get_pricing_row(provider, model, kind):
        return {"provider": provider, "model": model, "kind": kind}

    async def fake_upsert_pricing(**kwargs):
        upserts.append(kwargs)

    monkeypatch.setattr("billing.pricing_seed.get_pricing_row", fake_get_pricing_row)
    monkeypatch.setattr("billing.pricing_seed.upsert_pricing", fake_upsert_pricing)

    changed = await seed_pricing_defaults(
        force=True,
        markup_pct=Decimal("55"),
        uah_per_usd=Decimal("42.5"),
        rows=rows,
    )

    assert changed == 2
    assert len(upserts) == 2
    assert all(call["markup_pct"] == Decimal("55") for call in upserts)
    assert all(call["uah_per_usd"] == Decimal("42.5") for call in upserts)


@pytest.mark.asyncio
async def test_bootstrap_db_seeds_pricing_after_migrations(monkeypatch):
    from db import bootstrap as bootstrap_mod

    calls: list[str] = []

    async def fake_init_db():
        calls.append("init_db")

    async def fake_apply_migrations():
        calls.append("apply_migrations")

    async def fake_seed_pricing_defaults():
        calls.append("seed_pricing_defaults")

    monkeypatch.setattr(bootstrap_mod, "init_db", fake_init_db)
    monkeypatch.setattr(bootstrap_mod, "apply_migrations", fake_apply_migrations)
    monkeypatch.setattr(bootstrap_mod, "seed_pricing_defaults", fake_seed_pricing_defaults)

    await bootstrap_mod.bootstrap_db()

    assert calls == ["init_db", "apply_migrations", "seed_pricing_defaults"]


@pytest.mark.asyncio
async def test_seed_pricing_script_reports_actual_insert_count(monkeypatch, capsys):
    from scripts import seed_pricing as seed_script

    calls: list[str] = []

    async def fake_init_db():
        calls.append("init_db")

    async def fake_apply_migrations():
        calls.append("apply_migrations")

    async def fake_seed_pricing_defaults(**kwargs):
        calls.append(f"seed:{kwargs['force']}")
        return 3

    monkeypatch.setattr(seed_script, "init_db", fake_init_db)
    monkeypatch.setattr(seed_script, "apply_migrations", fake_apply_migrations)
    monkeypatch.setattr(seed_script, "seed_pricing_defaults", fake_seed_pricing_defaults)
    monkeypatch.setenv("BILLING_DEFAULT_MARKUP_PCT", "45")
    monkeypatch.setenv("BILLING_DEFAULT_UAH_PER_USD", "41.25")

    result = await seed_script.main(force=False)
    out = capsys.readouterr().out

    assert result == 0
    assert calls == ["init_db", "apply_migrations", "seed:False"]
    assert "inserted 3 pricing rows" in out
    assert f"skipped {len(seed_script.DEFAULT_PRICING_ROWS) - 3}" in out
