"""Handler for unknown commands or messages received by the Telegram bot."""

import logging

from aiogram import Router
from aiogram.types import Message

logger = logging.getLogger(__name__)
catch_all_router = Router(name="catch_all_router")


@catch_all_router.message()
async def handle_unknown_command_or_message(message: Message, _: callable) -> None:
    """Handles any message that isn't caught by other command or message handlers."""
    if not message.text or not message.from_user:  # Ignore non-text messages or messages without user
        return

    logger.debug("Received unknown message/command from user %s: '%s...'", message.from_user.id, message.text[:50])

    if message.text.startswith("/"):
        await message.reply(_("Unknown command. Use /help to see available commands."))
    else:
        pass
