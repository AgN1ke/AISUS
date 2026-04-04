from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

import yaml

from adapters.base import AbstractAdapter
from adapters.telegram_bot import TelegramBotAdapter
from adapters.userbot import TelethonUserbotAdapter
from app.message_logic import process_message
from core.env import telegram_bot_token

CONFIG_PATH = os.getenv("INSTANCES_CONFIG", "config/instances.yaml")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def _setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


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

    _setup_logging()
    logger.info("runtime.boot config_path=%s log_level=%s", CONFIG_PATH, LOG_LEVEL)
    await bootstrap_db()
    logger.info("runtime.db_bootstrap_ok")

    inst = _load_instances_from_file(CONFIG_PATH)
    if not inst:
        inst = _load_instances_from_env()
    if not inst:
        raise RuntimeError(
            "No valid runtime instances found. Set TG_BOT_TOKEN/MYAPI_BOT_TOKEN or provide a valid config/instances.yaml"
        )

    logger.info("runtime.instances_loaded count=%s", len(inst))
    adapters = []
    for d in inst:
        adapters.append(await _start_instance(d))

    stop_ev = asyncio.Event()

    def _stop(*_):
        logger.info("runtime.stop_signal_received")
        stop_ev.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(s, _stop)
        except NotImplementedError:
            pass

    await stop_ev.wait()
    for a in adapters:
        try:
            await a.stop()
        except Exception:
            pass
    logger.info("runtime.stopped")


if __name__ == "__main__":
    asyncio.run(main())
