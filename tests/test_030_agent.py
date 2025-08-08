import pytest, os
from agent.runner import _should_use_agent, run_agent, run_simple
from memory import memory_manager

CHAT=99903

@pytest.mark.asyncio
async def test_simple_vs_agent_switch():
    os.environ["THINKING_STRICT"]="1"
    await memory_manager.append_message(CHAT, "user", "звичайне питання")
    out1 = await run_simple(CHAT, "звичайне питання")
    assert "OK:" in out1

    q = "/think ПОШУК новини дня"
    out2 = await run_agent(CHAT, q)
    assert "OK:" in out2 or "Джерела" in out2
    assert _should_use_agent(q) is True

@pytest.mark.asyncio
async def test_should_use_agent_strict():
    os.environ["THINKING_STRICT"]="1"
    assert _should_use_agent("що нового") is True
    assert _should_use_agent("звичайне питання") is False
