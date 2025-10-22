"""Functions for interacting with the Telegram Bot API."""

import asyncio
import logging
from typing import Any

from aiogram import Bot as AiogramBot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.types import InaccessibleMessage, InlineKeyboardMarkup, Message
import pytalk

from bot.telegram_bot.formatters import format_telegram_user_display_name

ttstr = pytalk.instance.sdk.ttstr
logger = logging.getLogger(__name__)


async def send_telegram_message(
    bot_instance: AiogramBot,
    chat_id: int,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    disable_notification: bool = False,
    **kwargs: Any,
) -> bool:
    """Sends a single Telegram message, logs errors, and returns success status."""
    try:
        await bot_instance.send_message(
            chat_id=chat_id,
            reply_markup=reply_markup,
            disable_notification=disable_notification,
            **kwargs,
        )
        logger.debug(
            "Message sent to %s. Silent: %s, kwargs used: %s",
            chat_id,
            disable_notification,
            kwargs,
        )
    except TelegramForbiddenError:
        # Re-raise this specific error to be caught by the broadcaster
        # which has more context to handle it (e.g., delete the user).
        raise
    except TelegramAPIError as e:
        logger.warning("Failed to send message to chat_id %s: %s", chat_id, e)
        return False
    else:
        return True


async def get_display_names_for_ids(bot: AiogramBot, ids: list[int]) -> dict[int, str]:
    """Fetches display names for a list of Telegram IDs concurrently.

    Returns a dictionary mapping each ID to its display name.
    If an ID cannot be fetched, it will be mapped to its string representation.
    """
    if not ids:
        return {}

    display_names: dict[int, str] = {user_id: str(user_id) for user_id in ids}

    async def _fetch_and_set_name(user_id: int) -> None:
        """Fetches a user's display name and sets it in the parent scope dictionary."""
        try:
            chat_info = await bot.get_chat(user_id)
            display_names[user_id] = format_telegram_user_display_name(chat_info)
        except TelegramAPIError as e:
            logger.warning(
                "Could not fetch chat info for user_id %s. Falling back to ID. "
                "Error: %s",
                user_id,
                e,
            )
            # The fallback to str(user_id) is already set during initialization.

    try:
        async with asyncio.TaskGroup() as tg:
            for user_id in ids:
                tg.create_task(_fetch_and_set_name(user_id))
    except* Exception:
        logger.exception("Unexpected error group in get_display_names_for_ids")

    return display_names


async def get_display_name_for_id(bot: AiogramBot, user_id: int) -> str:
    """Fetches the display name for a single user ID."""
    try:
        chat_info = await bot.get_chat(user_id)
        return format_telegram_user_display_name(chat_info)
    except TelegramAPIError:
        logger.warning("Could not fetch chat info for user %s", user_id)
        return str(user_id)


async def delete_message(
    message: Message | InaccessibleMessage, log_context_message: str = "message"
) -> bool:
    """Deletes a message, catching TelegramAPIErrors and logging them.

    :param message: The aiogram.types.Message object to delete.
    :param log_context_message: A string to include in the log message for context
                                (e.g., "user settings command", "user menu command").
    :return: True if deletion was successful or if the message was already
        deleted/not found, False if another TelegramAPIError occurred.
    """
    if not isinstance(message, Message):
        return False

    try:
        await message.delete()
    except TelegramBadRequest as e:
        # Specific check for errors indicating the message can't be deleted
        # because it's too old,
        # doesn't exist, or the bot doesn't have rights. These are often not
        # critical failures
        # for the calling function's flow.
        if (
            "message to delete not found" in str(e).lower()
            or "message can't be deleted" in str(e).lower()
            or "message identifier is not specified" in str(e).lower()
        ):  # Should not happen with Message obj
            logger.info(
                "Could not delete %s (message likely already gone or "
                "permissions issue): %s",
                log_context_message,
                e,
            )
            return True  # Treat as "handled" or "not an issue for caller"
        logger.warning(
            "TelegramBadRequest when trying to delete %s: %s", log_context_message, e
        )
        return False  # Other bad requests might be more problematic
    except TelegramAPIError as e:
        # Catches other errors like Forbidden, etc.
        logger.warning(
            "Could not delete %s due to TelegramAPIError: %s", log_context_message, e
        )
        return False
    except (RuntimeError, TypeError):
        # Catch any other unexpected error
        logger.exception(
            "Unexpected error when trying to delete %s.", log_context_message
        )
        return False
    else:
        return True
