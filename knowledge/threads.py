# knowledge/threads.py
from __future__ import annotations
import os
from typing import Optional, List, Dict
from db.knowledge_repository import upsert_thread, get_message, insert_message, get_thread, set_thread_summary, fetch_thread_messages
from memory.summarizer import summarize_block

THREAD_SUMMARY_EVERY_N = int(os.getenv("THREAD_SUMMARY_EVERY_N", "8"))
THREAD_SUMMARY_LOOKBACK = int(os.getenv("THREAD_SUMMARY_LOOKBACK", "20"))

def _kind_from_flags(has_photo: bool, has_voice: bool, has_video: bool, has_doc: bool) -> str:
    if has_photo: return "photo"
    if has_voice: return "voice"
    if has_video: return "video"
    if has_doc:   return "doc"
    return "text"

async def _maybe_root_from_db(chat_id: int, replied_msg_id: int) -> Optional[int]:
    row = await get_message(chat_id, replied_msg_id)
    if not row:
        return replied_msg_id
    return row.get("thread_root_msg_id") or replied_msg_id

async def build_thread_summary_if_needed(chat_id: int, root_id: int):
    """
    Якщо в треді накопичилось достатньо повідомлень (кожні N),
    робимо короткий topic_summary на основі останніх LOOKBACK повідомлень.
    """
    msgs = await fetch_thread_messages(chat_id, root_id, limit=THREAD_SUMMARY_LOOKBACK)
    if not msgs:
        return

    thr = await get_thread(chat_id, root_id)
    if thr and thr.get("topic_summary"):
        if len(msgs) % THREAD_SUMMARY_EVERY_N != 0:
            return

    block = []
    for r in reversed(msgs):
        txt = (r.get("text") or r.get("caption_text") or "").strip()
        if not txt:
            continue
        block.append({"role": "user", "content": txt})

    if not block:
        return

    res = await summarize_block(block)
    await set_thread_summary(chat_id, root_id, res["summary"])

# ---- PTB інтеграція ----
async def handle_message_ptb(update, context):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else None

    has_photo = bool(getattr(msg, "photo", None))
    has_voice = bool(getattr(msg, "voice", None))
    has_video = bool(getattr(msg, "video", None))
    has_doc   = bool(getattr(msg, "document", None))

    kind = _kind_from_flags(has_photo, has_voice, has_video, has_doc)
    text = (msg.text or "") if kind == "text" else (msg.text or "")
    caption = (msg.caption or "") if getattr(msg, "caption", None) else None
    has_media = has_photo or has_voice or has_video or has_doc

    root_id: Optional[int] = None
    if msg.reply_to_message:
        root_id = await _maybe_root_from_db(chat_id, msg.reply_to_message.message_id)
        await upsert_thread(chat_id, root_id)

    await insert_message(chat_id, msg.message_id, user_id, kind, text, caption, has_media, root_id)

    if root_id:
        await build_thread_summary_if_needed(chat_id, root_id)

# ---- Telethon інтеграція ----
async def handle_message_telethon(event):
    msg = event.message
    chat_id = event.chat_id
    user_id = (await event.get_sender()).id if event.sender_id else None

    has_photo = bool(msg.photo)
    has_voice = bool(getattr(msg, "voice", None)) or (msg.document and getattr(msg.document.attributes[0], "voice", False))
    has_video = bool(msg.video)
    has_doc   = bool(msg.document) and not has_photo and not has_video

    kind = _kind_from_flags(has_photo, has_voice, has_video, has_doc)
    text = (msg.message or "") if kind == "text" else (msg.message or "")
    caption = None
    has_media = has_photo or has_voice or has_video or has_doc

    root_id: Optional[int] = None
    if msg.reply_to and msg.reply_to.reply_to_msg_id:
        root_id = await _maybe_root_from_db(chat_id, msg.reply_to.reply_to_msg_id)
        await upsert_thread(chat_id, root_id)

    await insert_message(chat_id, msg.id, user_id, kind, text, caption, has_media, root_id)

    if root_id:
        await build_thread_summary_if_needed(chat_id, root_id)
