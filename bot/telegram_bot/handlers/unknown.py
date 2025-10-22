"""Handler for unknown commands or messages received by the Telegram bot."""

from gettext import NullTranslations
import logging

from aiogram import Router
from aiogram.types import Message
from dishka.integrations.aiogram import FromDishka

from bot.telegram_bot.filters.subscription import IsSubscribed

logger = logging.getLogger(__name__)
catch_all_router = Router(name="catch_all_router")


@catch_all_router.message(IsSubscribed())
async def on_unknown_message(
    message: Message, translator: FromDishka[NullTranslations]
) -> None:
    """Handles any message that isn't caught by other command or message handlers."""
    _ = translator.gettext  # Assign for usage if this was the intent
    if (
        not message.text or not message.from_user
    ):  # Ignore non-text messages or messages without user
        return

    logger.debug(
        "Received unknown message/command from user %s: '%s...'",
        message.from_user.id,
        message.text[:50],
    )

    if message.text.startswith("/"):
        await message.reply(_("Unknown command. Use /help to see available commands."))
