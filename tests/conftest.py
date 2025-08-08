import os, asyncio, uuid, contextlib, shutil
import pytest
from db.connection import init_db, close_db, get_db_config
from db.migrate import apply_migrations

@pytest.fixture(scope="session", autouse=True)
def _load_env():
    # Мінімальні дефолти для тестів
    os.environ.setdefault("DB_HOST", "127.0.0.1")
    os.environ.setdefault("DB_PORT", "3306")
    os.environ.setdefault("DB_NAME", "aisus_test")
    os.environ.setdefault("DB_USER", "aisus")
    os.environ.setdefault("DB_PASS", "VeryStrongPassword!")
    os.environ.setdefault("OPENAI_CHAT_MODEL", "gpt-5-chat-latest")
    os.environ.setdefault("OPENAI_REASONING_MODEL", "")  # reasoning вимкнено в більшості тестів
    os.environ.setdefault("THINKING_ENABLED", "1")
    os.environ.setdefault("SEARCH_ENABLED", "1")
    os.environ.setdefault("THINKING_STRICT", "1")
    os.environ.setdefault("MEMORY_RECENT_BUDGET", "1000")
    os.environ.setdefault("MEMORY_LONG_BUDGET", "2000")
    os.environ.setdefault("MEDIA_TMP_DIR", "/tmp/aisus_media_test")
    os.environ.setdefault("CHAT_JOIN_PASSWORD", "supersecret")
    return True

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
async def _db_migrated(_load_env, event_loop):
    # Підключаємось до тестової БД і застосовуємо міграції
    await init_db()
    await apply_migrations()
    yield
    await close_db()

# ---- Моки OpenAI та HTTP ----
class DummyOpenAIChat:
    def __init__(self, *a, **kw): pass
    def create(self, **kw):
        class _Obj: pass
        o = _Obj()
        msg = _Obj()
        if kw.get("tools"):
            msg.tool_calls = []
            text = "".join([m.get("content","") for m in kw.get("messages",[]) if isinstance(m, dict)])
            if "ПОШУК" in text:
                tc = _Obj()
                tc.id = "tool1"
                class Fn: pass
                fn = Fn(); fn.name="search_web"; fn.arguments='{"query":"test query","max_results":2}'
                tc.function = fn
                msg.tool_calls = [tc]
                msg.content = None
            else:
                msg.content = "OK: dummy answer"
        else:
            msg.tool_calls = None
            msg.content = "OK: dummy answer"
        choice = _Obj(); choice.message = msg
        o.choices = [choice]
        return o

@pytest.fixture(autouse=True)
def patch_openai(monkeypatch):
    import agent.llm as llm
    class DummyClient:
        def __init__(self, **kw): pass
        class chat:
            class completions:
                create = staticmethod(DummyOpenAIChat().create)
    monkeypatch.setattr(llm, "_client", DummyClient())
    import memory.summarizer as sm
    monkeypatch.setattr(sm, "_client", DummyClient())
    yield

@pytest.fixture(autouse=True)
def patch_http(monkeypatch):
    import agent.tools.web_search as ws
    async def _fake_search(query, max_results=None, recency_days=None):
        return [{"title":"A","url":"https://a.test","snippet":"s1"},
                {"title":"B","url":"https://b.test","snippet":"s2"}][: (max_results or 2)]
    monkeypatch.setattr(ws, "search_web", _fake_search, raising=True)

    import agent.tools.fetch_page as fp
    async def _fake_fetch(url: str) -> str:
        return f"TEXT({url})"
    monkeypatch.setattr(fp, "fetch_page", _fake_fetch, raising=True)
    yield

skip_no_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

@pytest.fixture(autouse=True)
def patch_tiktoken(monkeypatch):
    import core.tokens as tokens
    monkeypatch.setattr(tokens, "tiktoken", None)
    yield
