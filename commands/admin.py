from __future__ import annotations

async def handle_command(platform: str, update, text: str, bot_username: str) -> bool:
    """Handle simple admin commands like /mem and /health.

    Returns True if the command was handled.
    """
    cmd = text.strip().split()[0].lower()
    if cmd == "/mem":
        if platform == "ptb":
            await update.effective_message.reply_text("Memory stats")
        else:
            await update.reply("Memory stats")
        return True
    if cmd == "/health":
        if platform == "ptb":
            await update.effective_message.reply_text("OK")
        else:
            await update.reply("OK")
        return True
    return False
