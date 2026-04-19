from __future__ import annotations

import asyncio
import importlib
import sys
import types

from core import env
from db import connection


def _import_run_module(monkeypatch):
    fake_telethon = types.ModuleType("telethon")
    fake_telethon.TelegramClient = object
    fake_telethon.events = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "telethon", fake_telethon)
    sys.modules.pop("run", None)
    import run

    return importlib.reload(run)


def test_db_pool_size_default_and_override(monkeypatch):
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    assert env.db_pool_size() == 50
    assert connection.get_db_config()["maxsize"] == 50

    monkeypatch.setenv("DB_POOL_SIZE", "64")
    assert env.db_pool_size() == 64
    assert connection.get_db_config()["maxsize"] == 64


def test_llm_thread_pool_size_default_and_override(monkeypatch):
    monkeypatch.delenv("LLM_THREAD_POOL_SIZE", raising=False)
    assert env.llm_thread_pool_size() == 128

    monkeypatch.setenv("LLM_THREAD_POOL_SIZE", "32")
    assert env.llm_thread_pool_size() == 32


def test_configure_runtime_executor_sets_default_executor(monkeypatch):
    run = _import_run_module(monkeypatch)
    created = {}

    class FakeExecutor:
        def __init__(self, *, max_workers: int, thread_name_prefix: str):
            self.max_workers = max_workers
            self.thread_name_prefix = thread_name_prefix
            created["executor"] = self

    class FakeLoop:
        def __init__(self):
            self.executor = None

        def set_default_executor(self, executor):
            self.executor = executor

    monkeypatch.setattr(run, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(run, "llm_thread_pool_size", lambda: 96)
    monkeypatch.setattr(run, "db_pool_size", lambda: 50)

    loop = FakeLoop()
    executor = run.configure_runtime_executor(loop)

    assert executor is created["executor"]
    assert loop.executor is executor
    assert executor.max_workers == 96
    assert executor.thread_name_prefix == "smartest-llm"


def test_main_shuts_down_default_executor(monkeypatch):
    run = _import_run_module(monkeypatch)
    calls = []

    class FakeLoop:
        def set_default_executor(self, executor):
            calls.append(("set_default_executor", executor))

        def add_signal_handler(self, *_):
            calls.append(("add_signal_handler", None))

        async def shutdown_default_executor(self):
            calls.append(("shutdown_default_executor", None))

    class FakeExecutor:
        def __init__(self, *, max_workers: int, thread_name_prefix: str):
            self.max_workers = max_workers
            self.thread_name_prefix = thread_name_prefix

    async def fake_bootstrap_db():
        calls.append(("bootstrap_db", None))

    async def fake_start_instance(_):
        calls.append(("start_instance", None))
        class FakeAdapter:
            async def stop(self):
                calls.append(("adapter_stop", None))

        return FakeAdapter()

    def fake_load_instances_from_file(_):
        return []

    def fake_load_instances_from_env():
        return [{"name": "default", "type": "bot", "token": "x"}]

    async def fake_purge():
        calls.append(("purge", None))
        return 0

    def fake_start_scheduler():
        calls.append(("start_scheduler", None))

    def fake_stop_scheduler():
        calls.append(("stop_scheduler", None))

    class StopEvent:
        async def wait(self):
            calls.append(("wait", None))

    monkeypatch.setattr(run, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(run, "llm_thread_pool_size", lambda: 8)
    monkeypatch.setattr(run, "db_pool_size", lambda: 50)
    monkeypatch.setattr(run, "_start_instance", fake_start_instance)
    monkeypatch.setattr(run, "_load_instances_from_file", fake_load_instances_from_file)
    monkeypatch.setattr(run, "_load_instances_from_env", fake_load_instances_from_env)
    monkeypatch.setattr(run, "purge_stale_media_tmp", fake_purge)
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(asyncio, "Event", StopEvent)

    import db.bootstrap
    import memory.scheduler

    monkeypatch.setattr(db.bootstrap, "bootstrap_db", fake_bootstrap_db)
    monkeypatch.setattr(memory.scheduler, "start_scheduler", fake_start_scheduler)
    monkeypatch.setattr(memory.scheduler, "stop_scheduler", fake_stop_scheduler)

    asyncio.run(run.main())

    assert ("bootstrap_db", None) in calls
    assert ("start_scheduler", None) in calls
    assert ("wait", None) in calls
    assert ("stop_scheduler", None) in calls
    assert ("adapter_stop", None) in calls
    assert ("shutdown_default_executor", None) in calls
