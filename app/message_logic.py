from __future__ import annotations
import os, re
from adapters.base import UnifiedMessage
from db.settings_repository import get_settings, upsert_settings
from memory import memory_manager
from agent.runner import _should_use_agent, run_agent, run_simple
from media.router import handle_ptb_mention, handle_telethon_mention


def _has_mention_ptb(update, bot_username: str) -> bool:
    msg = update.effective_message
    ents = (msg.entities or []) + (msg.caption_entities or [])
    needle = f"@{bot_username}".lower()
    if any(e.type in ("mention", "text_mention") for e in ents):
        t = (msg.text or msg.caption or "") or ""
        if needle in t.lower():
            return True
    t = (msg.text or msg.caption or "") or ""
    return needle in t.lower()


def _has_mention_text(text: str, bot_username: str) -> bool:
    if not text or not bot_username:
        return False
    return f"@{bot_username}".lower() in text.lower()


async def process_message(msg: UnifiedMessage) -> None:
    chat_id = msg.chat_id
    text = (msg.text or msg.caption or "") or ""
    bot_username = msg.bot_username or ""

    st = await get_settings(chat_id) or {}
    authed = bool(st.get("auth_ok") or 0)

    mentioned = False
    if msg.platform == "ptb":
        mentioned = _has_mention_ptb(msg.raw_update, bot_username)
    else:
        mentioned = _has_mention_text(text, bot_username)

    if not authed:
        if mentioned:
            stripped = re.sub(rf"@{re.escape(bot_username)}", "", text, flags=re.I).strip()
            pw = stripped.split()[0] if stripped else ""
            if pw and pw == os.getenv("CHAT_JOIN_PASSWORD", ""):
                await upsert_settings(chat_id, auth_ok=True, mode=("userbot" if msg.platform == "telethon" else "bot"))
                if msg.platform == "ptb":
                    await msg.raw_update.effective_message.reply_text("✅ Пароль прийнято. Я готова працювати тут.")
                else:
                    await msg.raw_update.reply("✅ Пароль прийнято. Я готова працювати тут.")
                return
            else:
                if msg.platform == "ptb":
                    await msg.raw_update.effective_message.reply_text(f"🔒 Напиши: @{bot_username} <пароль>")
                else:
                    await msg.raw_update.reply(f"🔒 Напиши: @{bot_username} <пароль>")
                return
        return

    user_text = None
    if mentioned:
        if msg.platform == "ptb":
            context = getattr(msg.raw_update, "_bot", None)
            user_text = await handle_ptb_mention(msg.raw_update, context, bot_username)
        else:
            user_text = await handle_telethon_mention(msg.raw_update, bot_username)

    if user_text is None:
        base_text = text.strip()
        if not base_text:
            return
        await memory_manager.append_message(chat_id, "user", base_text)
        await memory_manager.ensure_budget(chat_id)
        user_text = base_text

    answer = await (run_agent(chat_id, user_text) if _should_use_agent(user_text) else run_simple(chat_id, user_text))
    if not answer:
        return

    if msg.platform == "ptb":
        await msg.raw_update.effective_message.reply_text(answer)
    else:
        await msg.raw_update.reply(answer)

    await memory_manager.append_message(chat_id, "assistant", answer)
    await memory_manager.ensure_budget(chat_id)
