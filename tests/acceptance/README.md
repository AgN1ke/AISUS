# Acceptance Tests

Product-invariant tests for `@saintaibot` (master branch).

Each test corresponds to a `B-NNN` invariant from
[`docs/project/behavior-audit.md`](../../docs/project/behavior-audit.md).
Methodology — see [`docs/project/testing-protocol.md`](../../docs/project/testing-protocol.md).

## Running

```bash
python -m pytest tests/acceptance/ -v
```

These tests do **not** require a live database, network, or LLM. They build
synthetic Telegram updates, run them through routing logic
(`MessageGeometry`, `UserTask`, `ExecutionPlan`), and verify decisions.

Typical run: ~15 seconds for the full suite.

## Status legend

- **PASS** — `🟢 GREEN` invariant from audit. Must stay green.
- **XFAIL** — `🟡 YELLOW` invariant. Known fragile, work in progress.
- **SKIP** — `🔴 RED` invariant or `🗑 DROP` decision. Documented broken state.

## Deploy gate

`deploy/deploy.cjs` runs `pytest tests/acceptance/ -x` before tarballing.
Failed gate → deploy blocked. Bypass with `SKIP_ACCEPTANCE=1` (audit-only).

## Current baseline (Session 101)

- 7 PASS — addressing in private/group, mention recognition, reply-to-bot,
  build_user_task with media reply target, search-gate function exists.
- 10 XFAIL — search citations broken, album splits, vision/video doesn't see media,
  speaker disambiguation drifts.
- 20 SKIP — voice commands `/a` `/v` fully broken, voice transcription pipeline
  fails, `/c` clear command unverified, multi-bot isolation broken,
  reasoning marker not implemented, B-070 domain-citations not implemented.

## Adding a new test

1. Pick the relevant `B-NNN` ID from `behavior-audit.md`.
2. Add `test_BNNN_<short_name>` to the appropriate `test_<category>.py`.
3. For 🟢 — no skip/xfail.
4. For 🟡 — `@pytest.mark.xfail(reason="B-NNN: <symptom>", strict=False)`.
5. For 🔴 — `@pytest.mark.skip(reason="B-NNN: <symptom>")`.

When fixing a 🔴 → 🟢: remove `@pytest.mark.skip`, write the actual assertion,
verify locally, push.

## Backlog (next sessions to make 🔴 → 🟢)

Priority order from user audit (Session 101):

1. **Voice commands** (B-007..B-015) — entire `/a` `/v` flow broken.
2. **Media vision** (B-016, B-018, B-019) — bot reacts but doesn't actually see media.
3. **Voice pipeline** (B-020, B-021, B-022) — STT fails with provider error.
4. **Albums** (B-024, B-025, B-026) — split into per-item responses.
5. **Multi-bot isolation** (B-049) — bare commands react in multi-bot chats.
6. **Citations** (B-070) — implement `[domain.com](url)` format.
7. **Reasoning marker** (B-069) — visible `🧠 [reasoning ON]` indicator.
