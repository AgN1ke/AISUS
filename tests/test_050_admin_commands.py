import pytest
from types import SimpleNamespace
from commands.admin import handle_command

class PTBReply:
    def __init__(self):
        self.messages=[]
    async def reply_text(self, m): self.messages.append(m)

class PTBUpdate:
    def __init__(self, chat_id=99905):
        self.effective_chat = SimpleNamespace(id=chat_id, type="private")
        self.effective_message = PTBReply()
        self.effective_user = SimpleNamespace(id=123)

@pytest.mark.asyncio
async def test_mem_and_health():
    upd = PTBUpdate()
    handled = await handle_command("ptb", upd, "/mem", "botname")
    assert handled is True
    handled = await handle_command("ptb", upd, "/health", "botname")
    assert handled is True
