"""Acceptance tests for category F (Reasoning) and B-069 (visible marker).

Maps to B-003..B-006, B-069 in behavior-audit.md.
"""
from __future__ import annotations

import pytest

from agent.runner import _needs_reasoning


# ===== B-003: /think prefix enables reasoning =====

def test_B003_think_prefix_enables_reasoning():
    assert _needs_reasoning("/think що буде якщо людство колонізує Марс?") is True
    assert _needs_reasoning("/THINK uppercase") is True


# ===== B-004 DROP: 🧠 emoji must NOT enable reasoning =====

def test_B004_brain_emoji_does_NOT_enable_reasoning():
    """B-004 DROP: emoji ненадійний — може випадково потрапити у текст."""
    assert _needs_reasoning("🧠 розклади по поличках") is False
    assert _needs_reasoning("привіт 🧠 справи") is False


# ===== B-005 DROP: 'use reasoning' / 'роздумай' must NOT enable reasoning =====

def test_B005_phrase_triggers_dropped():
    """B-005 DROP: фразові тригери прибрані — занадто розмиті, незмірні."""
    assert _needs_reasoning("use reasoning, проаналізуй ринок") is False
    assert _needs_reasoning("роздумай що буде далі") is False
    assert _needs_reasoning("step-by-step розпиши план") is False
    assert _needs_reasoning("запусти різонінг для цього") is False


# ===== B-003: empty / non-think text does NOT enable reasoning =====

def test_B003_normal_text_does_NOT_enable_reasoning():
    assert _needs_reasoning("привіт, як справи") is False
    assert _needs_reasoning("") is False
    assert _needs_reasoning("/c@saintaibot") is False


# ===== B-069 NEW: reasoning marker visible to user =====

def test_B069_reasoning_marker_constant_defined():
    """B-069 NEW: REASONING_MARKER має бути визначений у message_logic."""
    from app import message_logic
    assert hasattr(message_logic, "REASONING_MARKER")
    assert "reasoning ON" in message_logic.REASONING_MARKER
    assert "🧠" in message_logic.REASONING_MARKER


def test_B069_search_marker_also_defined():
    """B-042: search marker — теж повинен існувати."""
    from app import message_logic
    assert hasattr(message_logic, "SEARCH_PERFORMED_MARKER")
    assert "ПОШУК" in message_logic.SEARCH_PERFORMED_MARKER
