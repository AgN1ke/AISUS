from typing import Dict
from telegram import Update
from src.aisus.config_parser import ConfigReader


class AuthService:
    def __init__(self, config: ConfigReader) -> None:
        self.config = config
        self.authenticated_users: Dict[int, bool] = {}

    async def authenticate(self, update: Update, bot_username: str) -> bool:
        chat_id = update.effective_chat.id
        if self.authenticated_users.get(chat_id):
            return True
        password = self.config.get_system_messages().get("password", "")
        raw_text = (update.message.text or update.message.caption or "")
        message_text_for_auth = raw_text.replace(f"@{bot_username}", "").strip()
        if message_text_for_auth == password or password == "":
            self.authenticated_users[chat_id] = True
            await update.message.reply_text("Автентифікація успішна. Ви можете почати спілкування.")
            return True
        await update.message.reply_text("Будь ласка, введіть пароль для продовження.")
        return False

    async def ensure_auth_for_command(self, update: Update) -> bool:
        chat_id = update.effective_chat.id
        if self.authenticated_users.get(chat_id):
            return True
        password = self.config.get_system_messages().get("password", "")
        if password == "":
            self.authenticated_users[chat_id] = True
            return True
        await update.message.reply_text("Будь ласка, введіть пароль для продовження.")
        return False
