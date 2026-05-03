import pytest
from memory import memory_manager
import memory.manager as memory_manager_module
from db.memory_repository import (
    fetch_core_all,
    fetch_long_all,
    fetch_recent,
    recent_total_tokens,
)

CHAT=99901

@pytest.mark.asyncio
async def test_append_and_compress():
    for i in range(80):
        await memory_manager.append_message(CHAT, "user", f"msg {i} " + "x"*50)
    toks_before = await recent_total_tokens(CHAT)
    assert toks_before > 0
    await memory_manager.ensure_budget(CHAT)
    longs = await fetch_long_all(CHAT)
    recs = await fetch_recent(CHAT)
    assert len(longs) >= 1
    assert len(recs) >= 1

@pytest.mark.asyncio
async def test_select_context_uses_long_and_recent():
    ctx = await memory_manager.select_context(CHAT, user_query="msg", system_prompt="SYS")
    assert any(m["role"]=="system" for m in ctx)
    assert any("[LONG-MEMO]" in m["content"] for m in ctx if m["role"]=="system")
    assert any(m["role"] in ("user","assistant") for m in ctx)


@pytest.mark.asyncio
async def test_fetch_recent_limit_returns_latest_window():
    chat_id = 99911
    for i in range(5):
        await memory_manager.append_message(chat_id, "user", f"recent {i}")

    rows = await fetch_recent(chat_id, limit=2)

    assert [row["content"] for row in rows] == ["recent 3", "recent 4"]


@pytest.mark.asyncio
async def test_clear_all_removes_recent_long_and_core():
    chat_id = 99912
    await memory_manager.append_message(chat_id, "user", "alpha")
    await memory_manager.append_message(chat_id, "assistant", "beta")
    await memory_manager.ensure_budget(chat_id)
    await memory_manager_module.upsert_core_fact(
        chat_id,
        "chat.topic",
        "testing",
        "explicit",
        320,
        3,
    )

    await memory_manager.clear_all(chat_id)

    assert not await fetch_recent(chat_id)
    assert not await fetch_long_all(chat_id)
    assert not await fetch_core_all(chat_id)


def test_participant_fact_guard_requires_stable_identity_in_block():
    block = """
[CHAT-TURN]
sender_user_id: 111
sender_username: @AgNike
current_user_text: I am not a medic, I work in communications.
"""

    assert memory_manager_module._is_safe_participant_fact(
        "participant.user_111.profession",
        block,
    )
    assert memory_manager_module._is_safe_participant_fact(
        "participant.agnike.preference",
        block,
    )
    assert memory_manager_module._is_safe_participant_fact(
        "chat.recurring_topics",
        block,
    )
    assert not memory_manager_module._is_safe_participant_fact(
        "participant.user_222.profession",
        block,
    )
    assert not memory_manager_module._is_safe_participant_fact(
        "participant.zheka.profession",
        block,
    )


@pytest.mark.asyncio
async def test_save_profile_facts_does_not_mix_people_without_stable_identity(monkeypatch):
    saved = []

    async def fake_extract_profile_facts(block_text, core_context):
        return [
            {
                "key": "participant.user_111.profession",
                "value": "communications person",
                "source": "explicit",
                "confidence": 320,
            },
            {
                "key": "participant.user_222.profession",
                "value": "doctor",
                "source": "llm_extracted",
                "confidence": 230,
            },
            {
                "key": "chat.recurring_topics",
                "value": "memory architecture",
                "source": "llm_extracted",
                "confidence": 230,
            },
        ]

    async def fake_core_total_tokens(chat_id):
        return 0

    async def fake_fetch_core_fact(chat_id, key):
        return None

    async def fake_upsert_core_fact(chat_id, key, value, source, confidence, tokens):
        saved.append((key, value, source, confidence))

    monkeypatch.setattr("memory.manager.extract_profile_facts", fake_extract_profile_facts)
    monkeypatch.setattr("memory.manager.core_total_tokens", fake_core_total_tokens)
    monkeypatch.setattr("memory.manager.fetch_core_fact", fake_fetch_core_fact)
    monkeypatch.setattr("memory.manager.upsert_core_fact", fake_upsert_core_fact)
    monkeypatch.setattr("memory.manager.count_tokens_text", lambda text, model: 1)

    block = """
[CHAT-TURN]
sender_user_id: 111
sender_username: @AgNike
current_user_text: I am not a medic, I work in communications.
"""

    await memory_manager.__class__()._save_profile_facts(777, block, "")

    keys = [item[0] for item in saved]
    assert "participant.user_111.profession" in keys
    assert "chat.recurring_topics" in keys
    assert "participant.user_222.profession" not in keys
