import os, sys, asyncio, signal, yaml
from adapters.telegram_bot import TelegramBotAdapter
from adapters.userbot import TelethonUserbotAdapter
from adapters.base import AbstractAdapter
from app.message_logic import process_message

CONFIG_PATH = os.getenv("INSTANCES_CONFIG", "config/instances.yaml")

async def _start_instance(defn) -> AbstractAdapter:
    t = (defn.get("type") or os.getenv("DEFAULT_INSTANCE_TYPE", "bot")).lower()
    name = defn.get("name") or f"{t}-instance"
    if t == "bot":
        token = defn.get("token") or os.getenv("TG_BOT_TOKEN")
        assert token, "Bot token missing"
        adapter = TelegramBotAdapter(name=name, token=token)
    elif t == "userbot":
        api_id = defn.get("api_id") or os.getenv("TELETHON_API_ID")
        api_hash = defn.get("api_hash") or os.getenv("TELETHON_API_HASH")
        session = defn.get("session") or os.getenv("TELETHON_SESSION_PATH") or os.path.join(os.getenv("TELETHON_SESSION_DIR", "./sessions"), f"{name}.session")
        assert api_id and api_hash, "Telethon API credentials missing"
        adapter = TelethonUserbotAdapter(name=name, api_id=int(api_id), api_hash=api_hash, session_path=session)
    else:
        raise RuntimeError(f"Unknown instance type: {t}")

    async def handler(msg):
        try:
            await process_message(msg)
        except Exception as e:
            print(f"[{name}] handler error: {e}", file=sys.stderr)
    asyncio.create_task(adapter.start(handler))
    return adapter

async def main():
    from db.bootstrap import bootstrap_db
    await bootstrap_db()

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    inst = cfg.get("instances") or []
    if not inst:
        inst = [{
            "name": "default",
            "type": os.getenv("DEFAULT_INSTANCE_TYPE", "bot"),
            "token": os.getenv("TG_BOT_TOKEN"),
            "api_id": os.getenv("TELETHON_API_ID"),
            "api_hash": os.getenv("TELETHON_API_HASH"),
            "session": os.getenv("TELETHON_SESSION_PATH"),
        }]

    adapters = []
    for d in inst:
        adapters.append(await _start_instance(d))

    stop_ev = asyncio.Event()

    def _stop(*_):
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

if __name__ == "__main__":
    asyncio.run(main())
