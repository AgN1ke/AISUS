from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from concurrent.futures import ThreadPoolExecutor

import yaml

from adapters.base import AbstractAdapter
from adapters.telegram_bot import TelegramBotAdapter
from adapters.userbot import TelethonUserbotAdapter
from app.message_logic import process_message
from core.env import db_pool_size, llm_thread_pool_size, telegram_bot_token
from core.logging_setup import setup_logging
from media.downloader import purge_stale_media_tmp

CONFIG_PATH = os.getenv("INSTANCES_CONFIG", "config/instances.yaml")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def _setup_logging() -> None:
    setup_logging("smartest-bot", LOG_LEVEL, stream=sys.stdout, force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


def configure_runtime_executor(loop: asyncio.AbstractEventLoop) -> ThreadPoolExecutor:
    max_workers = llm_thread_pool_size()
    executor = ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="smartest-llm",
    )
    loop.set_default_executor(executor)
    logger.info(
        "runtime.executors_configured llm_thread_pool_size=%s db_pool_size=%s",
        max_workers,
        db_pool_size(),
    )
    return executor


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    token = value.strip().upper()
    return token.startswith("PUT_YOUR_") or token.startswith("YOUR_")


def _load_instances_from_env() -> list[dict]:
    token = telegram_bot_token()
    if not token:
        return []
    return [
        {
            "name": "default",
            "type": os.getenv("DEFAULT_INSTANCE_TYPE", "bot"),
            "token": token,
            "api_id": os.getenv("TELETHON_API_ID"),
            "api_hash": os.getenv("TELETHON_API_HASH"),
            "session": os.getenv("TELETHON_SESSION_PATH"),
        }
    ]


def _load_instances_from_file(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    instances = []
    for item in cfg.get("instances") or []:
        inst = dict(item)
        inst_type = (inst.get("type") or "bot").lower()
        if inst_type == "bot" and _is_placeholder(inst.get("token")):
            continue
        if inst_type == "userbot" and (
            _is_placeholder(str(inst.get("api_id") or ""))
            or _is_placeholder(inst.get("api_hash"))
        ):
            continue
        instances.append(inst)
    return instances


async def _start_instance(defn) -> AbstractAdapter:
    t = (defn.get("type") or os.getenv("DEFAULT_INSTANCE_TYPE", "bot")).lower()
    name = defn.get("name") or f"{t}-instance"
    logger.info("runtime.start_instance name=%s type=%s", name, t)
    if t == "bot":
        token = defn.get("token") or telegram_bot_token()
        assert token, "Bot token missing"
        adapter = TelegramBotAdapter(name=name, token=token)
    elif t == "userbot":
        api_id = defn.get("api_id") or os.getenv("TELETHON_API_ID")
        api_hash = defn.get("api_hash") or os.getenv("TELETHON_API_HASH")
        session = (
            defn.get("session")
            or os.getenv("TELETHON_SESSION_PATH")
            or os.path.join(
                os.getenv("TELETHON_SESSION_DIR", "./sessions"), f"{name}.session"
            )
        )
        assert api_id and api_hash, "Telethon API credentials missing"
        adapter = TelethonUserbotAdapter(
            name=name, api_id=int(api_id), api_hash=api_hash, session_path=session
        )
    else:
        raise RuntimeError(f"Unknown instance type: {t}")

    async def handler(msg):
        try:
            await process_message(msg)
        except Exception as e:
            logger.exception(
                "runtime.handler_error instance=%s platform=%s chat_id=%s message_id=%s error=%s",
                name,
                getattr(msg, "platform", None),
                getattr(msg, "chat_id", None),
                getattr(msg, "message_id", None),
                e,
            )

    asyncio.create_task(adapter.start(handler))
    return adapter


async def main():
    from db.bootstrap import bootstrap_db
    from memory.scheduler import start_scheduler, stop_scheduler

    _setup_logging()
    logger.info("runtime.boot config_path=%s log_level=%s", CONFIG_PATH, LOG_LEVEL)
    loop = asyncio.get_running_loop()
    executor = configure_runtime_executor(loop)
    from agent.llm import set_main_event_loop
    set_main_event_loop(loop)
    adapters = []
    scheduler_started = False
    try:
        removed = await purge_stale_media_tmp()
        logger.info("runtime.media_tmp_purged removed=%s", removed)
    except Exception:
        logger.exception("runtime.media_tmp_purge_failed")
    try:
        await bootstrap_db()
        logger.info("runtime.db_bootstrap_ok")

        start_scheduler()
        scheduler_started = True

        inst = _load_instances_from_file(CONFIG_PATH)
        if not inst:
            inst = _load_instances_from_env()
        if not inst:
            raise RuntimeError(
                "No valid runtime instances found. Set TG_BOT_TOKEN/MYAPI_BOT_TOKEN or provide a valid config/instances.yaml"
            )

        logger.info("runtime.instances_loaded count=%s", len(inst))
        for d in inst:
            adapters.append(await _start_instance(d))

        stop_ev = asyncio.Event()

        def _stop(*_):
            logger.info("runtime.stop_signal_received")
            stop_ev.set()

        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(s, _stop)
            except NotImplementedError:
                pass

        await stop_ev.wait()
    finally:
        if scheduler_started:
            try:
                stop_scheduler()
            except Exception:
                logger.exception("runtime.scheduler_stop_failed")
        for a in adapters:
            try:
                await a.stop()
            except Exception:
                logger.exception("runtime.adapter_stop_failed name=%s", getattr(a, "name", None))
        try:
            await loop.shutdown_default_executor()
        except Exception:
            logger.exception("runtime.executor_shutdown_failed")
        logger.info("runtime.stopped")


if __name__ == "__main__":
    asyncio.run(main())
