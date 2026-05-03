"""Acceptance tests for category F (Reasoning) and B-069 (new debug marker).

Maps to B-003..B-006, B-044, B-069.
"""
from __future__ import annotations

import pytest


@pytest.mark.skip(reason="B-003 PENDING: /think reasoning trigger — needs B-069 marker to verify")
@pytest.mark.asyncio
async def test_B003_think_prefix_enables_reasoning():
    pass


@pytest.mark.skip(reason="B-004 DROP: 🧠 emoji trigger — користувач хоче прибрати")
@pytest.mark.asyncio
async def test_B004_brain_emoji_trigger_dropped():
    pass


@pytest.mark.skip(reason="B-005 DROP: 'use reasoning' / 'запусти різонінг' — користувач хоче прибрати")
@pytest.mark.asyncio
async def test_B005_phrase_triggers_dropped():
    pass


@pytest.mark.skip(
    reason=(
        "B-069 NEW: visible reasoning marker `🧠 [reasoning ON]` at end of response "
        "when /think activated. Required so user can verify reasoning happened."
    )
)
@pytest.mark.asyncio
async def test_B069_reasoning_marker_appended_when_active():
    pass
