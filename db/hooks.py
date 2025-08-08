from typing import Optional

from .repositories import upsert_chat, upsert_participant


# --- PTB (python-telegram-bot) варіант ---
async def track_chat_and_user_ptb(update, context, lang: Optional[str] = None):
    chat = update.effective_chat
    user = update.effective_user
    title = getattr(chat, "title", None)
    await upsert_chat(chat.id, title, lang)

    display_name = " ".join(filter(None, [user.first_name, user.last_name])) or user.username or str(user.id)
    await upsert_participant(chat.id, user.id, user.username, display_name)


# --- Telethon варіант ---
async def track_chat_and_user_telethon(event, lang: Optional[str] = None):
    # event: telethon.events.newmessage.NewMessage.Event
    chat = await event.get_chat()
    sender = await event.get_sender()
    chat_id = event.chat_id

    # Назва чату або ім'я співрозмовника у приваті
    title = getattr(chat, "title", None) or getattr(chat, "first_name", None)

    await upsert_chat(chat_id, title, lang)

    # Формуємо display_name
    first = getattr(sender, "first_name", None)
    last = getattr(sender, "last_name", None)
    username = getattr(sender, "username", None)
    display_name = " ".join(filter(None, [first, last])) or username or str(getattr(sender, "id", chat_id))
    await upsert_participant(chat_id, getattr(sender, "id", chat_id), username, display_name)
