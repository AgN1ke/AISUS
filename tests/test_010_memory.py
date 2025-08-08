import pytest
from memory import memory_manager
from db.memory_repository import fetch_long_all, fetch_recent, recent_total_tokens

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
