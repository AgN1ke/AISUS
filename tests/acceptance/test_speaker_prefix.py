"""Acceptance tests for category G — speaker disambiguation in groups.

Maps to B-046, B-048, B-030, B-036 in behavior-audit.md.

The fix: working memory exposes [Speaker: <name>] header on each user turn,
parsed from the [CHAT-TURN] system block that precedes it. The technical
block itself is dropped from the prompt — message_ids/timestamps are noise.
"""
from __future__ import annotations

from memory.manager import (
    _annotate_recent_rows,
    _speaker_label_from_fields,
    _structured_fields,
)


# ===== _structured_fields parses key:value lines =====


def test_structured_fields_parses_chat_turn_block():
    content = (
        "[CHAT-TURN]\n"
        "chat_type: group\n"
        "sender: Микита Загамула @ag\n"
        "sender_user_id: 123\n"
        "sender_username: @ag\n"
        "sender_display_name: Микита Загамула\n"
        "addressed_via_mention: true\n"
        "reply_to_bot: false\n"
    )
    fields = _structured_fields(content)
    assert fields["chat_type"] == "group"
    assert fields["sender_user_id"] == "123"
    assert fields["sender_username"] == "@ag"
    assert fields["sender_display_name"] == "Микита Загамула"
    assert fields["addressed_via_mention"] == "true"


# ===== _speaker_label_from_fields priority order =====


def test_speaker_label_prefers_display_plus_username():
    fields = {
        "sender_display_name": "Микита Загамула",
        "sender_username": "ag",
        "sender_user_id": "999",
    }
    assert _speaker_label_from_fields(fields) == "Микита Загамула (@ag)"


def test_speaker_label_falls_back_to_display_only():
    fields = {"sender_display_name": "Микита Загамула"}
    assert _speaker_label_from_fields(fields) == "Микита Загамула"


def test_speaker_label_falls_back_to_username():
    fields = {"sender_username": "ag"}
    assert _speaker_label_from_fields(fields) == "@ag"


def test_speaker_label_falls_back_to_user_id():
    fields = {"sender_user_id": "12345"}
    assert _speaker_label_from_fields(fields) == "user_12345"


def test_speaker_label_empty_when_no_fields():
    assert _speaker_label_from_fields({}) == ""


# ===== _annotate_recent_rows: speaker prefix on user messages =====


def test_B046_speaker_prefix_attached_to_user_turn():
    """B-046: each user turn gets [Speaker: ...] header so model knows who said what."""
    rows = [
        {
            "role": "system",
            "content": (
                "[CHAT-TURN]\n"
                "sender_display_name: Микита Загамула\n"
                "sender_username: @ag\n"
                "addressed_via_mention: true\n"
            ),
        },
        {"role": "user", "content": "я люблю каву"},
    ]
    out = _annotate_recent_rows(rows)
    assert len(out) == 1  # [CHAT-TURN] dropped, only user msg remains
    assert out[0]["role"] == "user"
    assert "[Speaker: Микита Загамула (@ag)]" in out[0]["content"]
    assert "addressed_via_mention: true" in out[0]["content"]
    assert "я люблю каву" in out[0]["content"]


def test_B046_two_speakers_in_group_dont_collide():
    """B-046: коли в групі говорять два різних учасники — кожен user-turn
    отримує СВІЙ speaker label, не плутаються."""
    rows = [
        {
            "role": "system",
            "content": (
                "[CHAT-TURN]\nsender_display_name: Микита\n"
                "sender_username: @ag\n"
            ),
        },
        {"role": "user", "content": "я люблю каву"},
        {
            "role": "system",
            "content": (
                "[CHAT-TURN]\nsender_display_name: Олена\n"
                "sender_username: @olena\n"
            ),
        },
        {"role": "user", "content": "я люблю чай"},
        {"role": "assistant", "content": "Зрозумів — ви різне любите."},
    ]
    out = _annotate_recent_rows(rows)
    user_msgs = [m for m in out if m["role"] == "user"]
    assert len(user_msgs) == 2
    assert "[Speaker: Микита (@ag)]" in user_msgs[0]["content"]
    assert "я люблю каву" in user_msgs[0]["content"]
    assert "[Speaker: Олена (@olena)]" in user_msgs[1]["content"]
    assert "я люблю чай" in user_msgs[1]["content"]


def test_B046_chat_turn_block_dropped_from_prompt():
    """B-046: technical [CHAT-TURN] block has timestamps/message_ids — noise
    for LLM — must be removed from prompt."""
    rows = [
        {
            "role": "system",
            "content": "[CHAT-TURN]\nsender_display_name: Микита\nchat_type: group",
        },
        {"role": "user", "content": "тест"},
    ]
    out = _annotate_recent_rows(rows)
    # No raw [CHAT-TURN] block remains
    assert not any("[CHAT-TURN]" in (m.get("content") or "") for m in out)


def test_B046_other_system_blocks_pass_through():
    """B-046: only [CHAT-TURN] is dropped; [SEARCH], [LONG-MEMO], [CORE] etc.
    keep role=system and pass through unchanged."""
    rows = [
        {"role": "system", "content": "[CORE]\nrole: інженер"},
        {
            "role": "system",
            "content": "[CHAT-TURN]\nsender_display_name: Микита",
        },
        {"role": "user", "content": "що ти про мене знаєш?"},
        {"role": "system", "content": "[SEARCH]\nrequest: щось"},
    ]
    out = _annotate_recent_rows(rows)
    contents = [m["content"] for m in out]
    assert any(c.startswith("[CORE]") for c in contents)
    assert any(c.startswith("[SEARCH]") for c in contents)
    assert not any("[CHAT-TURN]" in c for c in contents)


def test_B046_legacy_rows_without_chat_turn_pass_through():
    """B-046: rows without preceding [CHAT-TURN] (legacy data) — user msgs
    pass through without prefix, role preserved."""
    rows = [
        {"role": "user", "content": "старе повідомлення без turn-блоку"},
        {"role": "assistant", "content": "стара відповідь"},
    ]
    out = _annotate_recent_rows(rows)
    assert len(out) == 2
    assert out[0]["role"] == "user"
    assert out[0]["content"] == "старе повідомлення без turn-блоку"
    assert out[1]["role"] == "assistant"


def test_B030_reply_target_text_lifted_to_speaker_header():
    """B-030/B-036: reply_target_text from [CHAT-TURN] (truncated to 240 chars)
    appears in the speaker header, so model knows what user is replying to."""
    rows = [
        {
            "role": "system",
            "content": (
                "[CHAT-TURN]\nsender_display_name: Микита\n"
                "reply_to_bot: true\n"
                "reply_target_text: Бот раніше сказав щось важливе.\n"
            ),
        },
        {"role": "user", "content": "поясни детальніше"},
    ]
    out = _annotate_recent_rows(rows)
    assert "reply_target_text: Бот раніше сказав щось важливе." in out[0]["content"]
    assert "reply_to_bot: true" in out[0]["content"]


def test_B030_one_chat_turn_does_not_leak_to_next_user():
    """B-030 anti-rule: speaker label binds to NEXT user message only.
    If next thing is assistant or another system block — pending speaker is
    consumed by user OR cleared (so it doesn't leak to a later user turn)."""
    rows = [
        {
            "role": "system",
            "content": "[CHAT-TURN]\nsender_display_name: Микита\n",
        },
        {"role": "user", "content": "перше"},
        # No CHAT-TURN before next user — legacy data
        {"role": "user", "content": "друге без turn"},
    ]
    out = _annotate_recent_rows(rows)
    # First user has Микита label
    assert "Микита" in out[0]["content"]
    assert "перше" in out[0]["content"]
    # Second user has NO Микита label (pending was consumed)
    assert "Микита" not in out[1]["content"]
    assert out[1]["content"] == "друге без turn"
