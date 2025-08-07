"""Global error handler for the Telegram bot."""

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types.error_event import ErrorEvent
from dishka.integrations.aiogram import FromDishka

from bot.config import Settings
from bot.telegram_bot.types.bots import MessageBot

error_router = Router(name="error_router")
logger = logging.getLogger(__name__)


@error_router.errors()
async def universal_error_handler(
    event: ErrorEvent,
    bot: FromDishka[MessageBot],
    settings: FromDishka[Settings],
) -> bool:
    """Catches all exceptions that were not handled in other handlers."""
    logger.exception(
        "An error occurred while processing an update: %s",
        event.exception,
        exc_info=event.exception,
    )

    # Attempt to notify the user about the problem
    update_dict = event.update.model_dump(exclude_unset=True)
    chat_id = update_dict.get("message", {}).get("chat", {}).get(
        "id"
    ) or update_dict.get("callback_query", {}).get("from", {}).get("id")

    if chat_id:
        try:
            # Send a generic error message to the user
            await bot.send_message(
                chat_id,
                text="An unexpected error occurred. We are already working on fixing it. Please try again later.",
            )
        except TelegramAPIError:
            logger.exception("Failed to send the error message to user %s", chat_id)

    # Also, send a notification to the administrator
    admin_id = settings.telegram.admin_chat_id
    if admin_id:
        try:
            await bot.send_message(
                admin_id,
                f"<b>Critical Error!</b>\n"
                f"Type: {type(event.exception).__name__}\n"
                f"Error: {event.exception}\n"
                f"Update: <code>{event.update}</code>",
            )
        except TelegramAPIError:
            logger.exception(
                "Failed to send the critical error message to admin %s", admin_id
            )

    return True  # Tell the dispatcher that the error has been handled
