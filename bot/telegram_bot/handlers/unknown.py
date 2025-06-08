import logging
from typing import Any # Added for data type hint
from aiogram import Router
from aiogram.types import Message
# from bot.localization import get_text # Removed

logger = logging.getLogger(__name__)
catch_all_router = Router(name="catch_all_router")

@catch_all_router.message() # Catches any message not handled by other routers
async def handle_unknown_command_or_message(
    message: Message,
    data: dict[str, Any] # To get `_` from UserSettingsMiddleware
):
    _ = data["_"] # Translator function
    if not message.text or not message.from_user : # Ignore non-text messages or messages without user
        return

    # Log that an unknown command/message was received
    logger.debug(f"Received unknown message/command from user {message.from_user.id}: '{message.text[:50]}...'")

    if message.text.startswith("/"):
        await message.reply(_("Unknown command. Use /help to see available commands.")) # UNKNOWN_COMMAND
    else:
        pass
