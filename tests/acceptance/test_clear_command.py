"""Acceptance tests for /c clear command (B-001 .. B-002).

Maps to B-001, B-002 in behavior-audit.md.

B-001 GREEN after Session 102: bare /c in group blocked (multi-bot safety),
@bot /c form blocked, only /c@bot suffix form clears.
"""
from __future__ import annotations

import pytest

from app.message_logic import _is_clear_context_command


# ===== B-001: /c@bot clears, bare /c in group does NOT, @bot /c does NOT =====

def test_B001_c_with_bot_tag_in_group_clears():
    """/c@saintaibot in group → True (clears)."""
    assert _is_clear_context_command(
        "/c@saintaibot", "saintaibot", chat_type="group"
    ) is True


def test_B001_c_with_bot_tag_in_supergroup_clears():
    assert _is_clear_context_command(
        "/c@saintaibot", "saintaibot", chat_type="supergroup"
    ) is True


def test_B001_bare_c_in_group_does_NOT_clear():
    """B-001 anti-rule: bare /c in group must NOT clear (multi-bot safety)."""
    assert _is_clear_context_command(
        "/c", "saintaibot", chat_type="group"
    ) is False


def test_B001_bare_c_in_supergroup_does_NOT_clear():
    assert _is_clear_context_command(
        "/c", "saintaibot", chat_type="supergroup"
    ) is False


def test_B001_bare_c_in_private_clears():
    """In private, bare /c is fine (only one bot)."""
    assert _is_clear_context_command(
        "/c", "saintaibot", chat_type="private"
    ) is True


def test_B001_at_bot_then_c_does_NOT_clear():
    """B-001: '@saintaibot /c' (tag-then-command) must NOT clear."""
    assert _is_clear_context_command(
        "@saintaibot /c", "saintaibot", chat_type="group"
    ) is False


def test_B001_c_with_other_bot_tag_does_NOT_clear():
    """B-001: /c@otherbot must not clear our memory."""
    assert _is_clear_context_command(
        "/c@otherbot", "saintaibot", chat_type="group"
    ) is False


def test_B001_c_with_extra_text_does_NOT_clear():
    """/c followed by extra text → not a clear command."""
    assert _is_clear_context_command(
        "/c@saintaibot please", "saintaibot", chat_type="group"
    ) is False


# ===== B-002 still pending integration test =====

@pytest.mark.skip(
    reason=(
        "B-002 PENDING: after clear, bot must say memory empty, not hallucinate "
        "history. Needs end-to-end test with fake LLM response."
    )
)
def test_B002_after_clear_bot_does_not_hallucinate_history():
    pass
