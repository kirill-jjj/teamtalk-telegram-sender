"""Global error handler for the Telegram bot."""

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types.error_event import ErrorEvent
from aiogram.utils.formatting import Bold, Text
from dishka.integrations.aiogram import FromDishka

from bot.config import Settings
from bot.telegram_bot.types.bots import EventBot

error_router = Router(name="error_router")
logger = logging.getLogger(__name__)


@error_router.errors()
async def universal_error_handler(
    event: ErrorEvent,
    bot: FromDishka[EventBot],
    settings: FromDishka[Settings],
) -> bool:
    """Catches all exceptions that were not handled in other handlers."""

    def _(s: str) -> str:  # Placeholder for future gettext integration
        return s

    logger.exception(
        "An error occurred while processing an update: %s",
        event.exception,
        exc_info=event.exception,
    )

    update_dict = event.update.model_dump(exclude_unset=True)
    chat_id = update_dict.get("message", {}).get("chat", {}).get(
        "id"
    ) or update_dict.get("callback_query", {}).get("from", {}).get("id")

    if chat_id:
        try:
            user_error_message = _(
                "An unexpected error occurred. We are already working on fixing it. "
                "Please try again later."
            )
            await bot.send_message(chat_id, text=user_error_message)
        except TelegramAPIError:
            logger.exception("Failed to send the error message to user %s", chat_id)

    admin_id = settings.telegram.admin_chat_id
    if admin_id:
        content = Text(
            Bold("Critical Error!"),
            "\n\n",
            Bold("Type: "),
            type(event.exception).__name__,
            "\n",
            Bold("Error: "),
            str(event.exception),
            "\n\n",
            Bold("Update ID: "),
            event.update.update_id,
            "\n",
            Bold("Chat ID: "),
            str(chat_id or "N/A"),
        )
        try:
            await bot.send_message(admin_id, **content.as_kwargs())
        except TelegramAPIError:
            logger.exception(
                "Failed to send the critical error message to admin %s", admin_id
            )

    return True
