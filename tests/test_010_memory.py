import pytest
from db import memory_repository
from memory import memory_manager
from db.memory_repository import fetch_long_all, fetch_recent, recent_total_tokens

CHAT=99901

@pytest.mark.asyncio
async def test_append_and_compress(monkeypatch):
    monkeypatch.setattr("memory.manager._recent_budget", lambda: 200)
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
async def test_select_context_marks_empty_history(monkeypatch):
    async def fake_is_memory_persist_enabled(chat_id):
        return True

    async def fake_core_context_text(chat_id):
        return ""

    async def fake_select_long_relevant(chat_id, user_query):
        return [], []

    async def fake_fetch_recent(chat_id):
        return []

    monkeypatch.setattr(
        "memory.manager.is_memory_persist_enabled",
        fake_is_memory_persist_enabled,
    )
    monkeypatch.setattr(
        memory_manager,
        "_core_context_text",
        fake_core_context_text,
    )
    monkeypatch.setattr(
        memory_manager,
        "_select_long_relevant",
        fake_select_long_relevant,
    )
    monkeypatch.setattr("memory.manager.fetch_recent", fake_fetch_recent)

    ctx = await memory_manager.select_context(CHAT, user_query="про що ми говорили?", system_prompt="SYS")

    assert any(
        "[CONTEXT-STATE]" in m["content"] and "Не вигадуй" in m["content"]
        for m in ctx
        if m["role"] == "system"
    )


@pytest.mark.asyncio
async def test_clear_all_clears_recent_and_long(monkeypatch):
    calls = []

    async def fake_delete_recent_chat(chat_id):
        calls.append(("recent", chat_id))

    async def fake_delete_core_facts(chat_id):
        calls.append(("core", chat_id))

    async def fake_fetch_long_all(chat_id):
        calls.append(("fetch_long", chat_id))
        return [{"id": 1}, {"id": 2}]

    async def fake_delete_long_by_ids(ids):
        calls.append(("long", ids))

    monkeypatch.setattr("memory.manager.delete_recent_chat", fake_delete_recent_chat)
    monkeypatch.setattr("memory.manager.delete_core_facts", fake_delete_core_facts)
    monkeypatch.setattr("memory.manager.fetch_long_all", fake_fetch_long_all)
    monkeypatch.setattr("memory.manager.delete_long_by_ids", fake_delete_long_by_ids)

    manager = memory_manager.__class__()
    manager._last_consolidation[CHAT] = 123.0

    await manager.clear_all(CHAT)

    assert ("recent", CHAT) in calls
    assert ("core", CHAT) in calls
    assert ("fetch_long", CHAT) in calls
    assert ("long", [1, 2]) in calls
    assert CHAT not in manager._last_consolidation


@pytest.mark.asyncio
async def test_clear_global_clears_all_layers(monkeypatch):
    calls = []

    async def fake_delete_recent_all():
        calls.append("recent_all")

    async def fake_delete_long_all():
        calls.append("long_all")

    async def fake_delete_core_all():
        calls.append("core_all")

    monkeypatch.setattr("memory.manager.delete_recent_all", fake_delete_recent_all)
    monkeypatch.setattr("memory.manager.delete_long_all", fake_delete_long_all)
    monkeypatch.setattr("memory.manager.delete_core_all", fake_delete_core_all)

    manager = memory_manager.__class__()
    manager._last_consolidation[1] = 1.0
    manager._last_consolidation[2] = 2.0

    await manager.clear_global()

    assert calls == ["recent_all", "long_all", "core_all"]
    assert manager._last_consolidation == {}


@pytest.mark.asyncio
async def test_select_context_keeps_all_memory_layers_in_same_chat_scope(monkeypatch):
    calls = []

    async def fake_is_memory_persist_enabled(chat_id):
        calls.append(("persist", chat_id))
        return True

    async def fake_core_context_text(chat_id):
        calls.append(("core", chat_id))
        return "core fact"

    async def fake_select_long_relevant(chat_id, user_query):
        calls.append(("long", chat_id, user_query))
        return ([{"role": "system", "content": "[LONG-MEMO] long fact"}], [10])

    async def fake_fetch_recent(chat_id):
        calls.append(("recent", chat_id))
        return [
            {"role": "user", "content": "recent user", "tokens": 2},
            {"role": "assistant", "content": "recent assistant", "tokens": 2},
        ]

    async def fake_bump_long_usage(ids):
        calls.append(("bump", tuple(ids)))

    monkeypatch.setattr("memory.manager.is_memory_persist_enabled", fake_is_memory_persist_enabled)
    monkeypatch.setattr(memory_manager, "_core_context_text", fake_core_context_text)
    monkeypatch.setattr(memory_manager, "_select_long_relevant", fake_select_long_relevant)
    monkeypatch.setattr("memory.manager.fetch_recent", fake_fetch_recent)
    monkeypatch.setattr("memory.manager.bump_long_usage", fake_bump_long_usage)

    ctx = await memory_manager.select_context(555, user_query="що було?", system_prompt="SYS")

    assert ("persist", 555) in calls
    assert ("core", 555) in calls
    assert ("long", 555, "що було?") in calls
    assert ("recent", 555) in calls
    assert ("bump", (10,)) in calls
    assert any(m["content"] == "[LONG-MEMO] long fact" for m in ctx)
    assert any(m["content"] == "recent user" for m in ctx)
    assert any(m["content"] == "recent assistant" for m in ctx)


@pytest.mark.asyncio
async def test_fetch_recent_without_limit_scopes_to_chat_and_orders_ascending(monkeypatch):
    captured = {}

    async def fake_fetchall(sql, args=None, dict_cursor=True):
        captured["sql"] = " ".join(sql.split())
        captured["args"] = args
        captured["dict_cursor"] = dict_cursor
        return []

    monkeypatch.setattr(memory_repository, "fetchall", fake_fetchall)

    rows = await memory_repository.fetch_recent(321)

    assert rows == []
    assert "WHERE chat_id=%s" in captured["sql"]
    assert "ORDER BY pos ASC" in captured["sql"]
    assert "LIMIT" not in captured["sql"]
    assert captured["args"] == (321,)
    assert captured["dict_cursor"] is True


@pytest.mark.asyncio
async def test_fetch_recent_with_limit_reads_latest_window_for_same_chat(monkeypatch):
    captured = {}
    expected_rows = [
        {"pos": 41, "role": "user", "content": "newer-1", "tokens": 4, "created_at": None},
        {"pos": 42, "role": "assistant", "content": "newer-2", "tokens": 5, "created_at": None},
    ]

    async def fake_fetchall(sql, args=None, dict_cursor=True):
        captured["sql"] = " ".join(sql.split())
        captured["args"] = args
        captured["dict_cursor"] = dict_cursor
        return expected_rows

    monkeypatch.setattr(memory_repository, "fetchall", fake_fetchall)

    rows = await memory_repository.fetch_recent(654, limit=5)

    assert rows == expected_rows
    assert "FROM (" in captured["sql"]
    assert "WHERE chat_id=%s" in captured["sql"]
    assert "ORDER BY pos DESC LIMIT 5" in captured["sql"]
    assert "ORDER BY pos ASC" in captured["sql"]
    assert captured["args"] == (654,)
    assert captured["dict_cursor"] is True
