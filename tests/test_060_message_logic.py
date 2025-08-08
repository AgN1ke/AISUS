import pytest, os
from types import SimpleNamespace
from app.message_logic import process_message
from adapters.base import UnifiedMessage

class DummyPTBMessage:
    def __init__(self):
        self._sent=[]
    async def reply_text(self, t): self._sent.append(t)

@pytest.mark.asyncio
async def test_auth_flow_with_password():
    os.environ["CHAT_JOIN_PASSWORD"]="supersecret"
    upd_chat = SimpleNamespace(id=99906, type="group")
    msg = DummyPTBMessage()
    um = UnifiedMessage(platform="ptb", chat_id=99906, message_id=1, text="@botx supersecret", caption=None,
                        reply_to_message_id=None, has_photo=False, has_voice=False, has_video=False, has_document=False,
                        raw_update=SimpleNamespace(effective_chat=upd_chat, effective_message=msg), bot_username="botx")
    await process_message(um)
    assert any("Пароль прийнято" in m for m in msg._sent)
