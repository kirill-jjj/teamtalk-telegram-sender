"""Utility functions for Telegram bot operations, like sending messages and handling API errors."""

import asyncio
from collections.abc import Callable
import logging

# For type hinting Services
from typing import Any

from aiogram import Bot as AiogramBot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Chat, InlineKeyboardMarkup, Message
import pytalk
from pytalk.user import User as TeamTalkUser
from sqlalchemy.exc import SQLAlchemyError

from bot.config import Settings
from bot.constants import (
    DEFAULT_LANGUAGE,
)
from bot.database.engine import AsyncSessionFactoryType
from bot.models import UserSettings
from bot.services import notification_service, user_service
from bot.services.cache_service import CacheService

ttstr = pytalk.instance.sdk.ttstr
logger = logging.getLogger(__name__)


async def _handle_telegram_api_error(
    error: TelegramAPIError,
    chat_id: int,
    session_factory: AsyncSessionFactoryType,
    cache: CacheService,
) -> None:
    """Handles specific Telegram API errors using structural pattern matching."""
    logger.debug("Handling Telegram API error '%s' for chat_id %d", type(error).__name__, chat_id)

    match error:
        case TelegramForbiddenError() if "bot was blocked" in str(error) or "user is deactivated" in str(error):
            logger.warning("User %s blocked the bot or is deactivated. Deleting all user data...", chat_id)
            try:
                async with session_factory() as session:
                    success = await user_service.delete_user_profile(session, chat_id, cache=cache)
                if success:
                    logger.info("Successfully deleted all data for blocked/deactivated user %s.", chat_id)
                else:
                    logger.error(
                        "Failed to delete data for blocked/deactivated user %s, though an attempt was made.", chat_id
                    )
            except SQLAlchemyError:
                logger.exception("Failed to delete data for blocked/deactivated user %s from DB.", chat_id)

        case TelegramBadRequest() if "chat not found" in str(error):
            logger.warning("Chat not found for TG ID %s. Deleting all user data. Error: %s", chat_id, error)
            try:
                async with session_factory() as session:
                    delete_success = await user_service.delete_user_profile(session, chat_id, cache=cache)
                if delete_success:
                    logger.info("Successfully deleted all data for TG ID %s due to chat not found.", chat_id)
                else:
                    logger.error("Failed to delete all data for TG ID %s after chat not found.", chat_id)
            except SQLAlchemyError:
                logger.exception("Exception during full data cleanup for TG ID %s (chat not found).", chat_id)

        case TelegramForbiddenError() | TelegramBadRequest():
            logger.error("Unhandled Telegram Forbidden/Bad Request error for chat_id %s: %s", chat_id, error)

        case TelegramAPIError():
            logger.error("Unhandled Telegram API error for chat_id %s: %s", chat_id, error)


def _should_send_silently(chat_id: int, *, tt_user_is_online: bool, cache: CacheService) -> bool:
    """Checks if a message to a given chat_id should be sent silently."""
    recipient_settings = cache.get_user_settings(chat_id)

    if notification_service.is_user_subject_to_noon_check(recipient_settings) and tt_user_is_online:
        logger.debug(
            "Message to %s will be silent: linked user is online and NOON is subject to check "
            "(via notification_service).",
            chat_id,
        )
        return True

    return False


async def send_telegram_message(
    bot_instance: AiogramBot,
    chat_id: int,
    session_factory: AsyncSessionFactoryType,
    cache: CacheService,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    tt_user_is_online: bool = False,
    **kwargs: Any,  # noqa: ANN401
) -> bool:
    """Sends a single Telegram message to a user, handling potential errors."""
    send_silently = _should_send_silently(chat_id=chat_id, tt_user_is_online=tt_user_is_online, cache=cache)

    try:
        await bot_instance.send_message(
            chat_id=chat_id, reply_markup=reply_markup, disable_notification=send_silently, **kwargs
        )
        logger.debug("Message sent to %s. Silent: %s, kwargs used: %s", chat_id, send_silently, kwargs)
    except TelegramAPIError as e:
        await _handle_telegram_api_error(e, chat_id, session_factory=session_factory, cache=cache)
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

    chat_info_tasks: dict[int, asyncio.Task[Chat]] = {}
    try:
        async with asyncio.TaskGroup() as tg:
            for user_id in ids:
                task: asyncio.Task[Chat] = tg.create_task(bot.get_chat(user_id))
                chat_info_tasks[user_id] = task
    except* TelegramAPIError as eg:
        for error in eg.exceptions:
            # The specific user ID isn't easily available from the exception group,
            # so we log a general warning. The logic below will handle individual failures.
            logger.warning("Could not fetch chat info for at least one user: %s", error)

    display_names: dict[int, str] = {}
    for user_id, task in chat_info_tasks.items():
        if task.done() and not task.cancelled() and not task.exception():
            chat_result = task.result()
            display_names[user_id] = format_telegram_user_display_name(chat_result)
        else:
            if task.exception():
                logger.error("Failed to get chat info for TG ID %s due to an exception: %s", user_id, task.exception())
            # Fallback to the ID itself if fetching failed for any reason
            display_names[user_id] = str(user_id)

    return display_names


async def broadcast_to_users(
    bot_instance_to_use: AiogramBot,
    recipients_with_lang: list[tuple[int, str | None]],
    text_generator: Callable[[str | None], str],
    settings: Settings,
    cache: CacheService,
    session_factory: AsyncSessionFactoryType,
    online_users_cache_for_instance: dict[int, TeamTalkUser] | None = None,
    reply_markup_generator: Callable[[str | None, int], InlineKeyboardMarkup | None] | None = None,
) -> None:
    """Sends localized messages to a list of recipients using a TaskGroup for robustness."""
    if not bot_instance_to_use:
        logger.error("No Telegram bot instance provided to broadcast_to_users.")
        return

    try:
        async with asyncio.TaskGroup() as tg:
            for chat_id, lang_code in recipients_with_lang:
                language_code = lang_code or DEFAULT_LANGUAGE
                text = text_generator(language_code)
                current_reply_markup = (
                    reply_markup_generator(language_code, chat_id) if reply_markup_generator else None
                )

                user_settings: UserSettings | None = cache.get_user_settings(chat_id)
                individual_tt_user_is_online = False
                if user_settings and user_settings.teamtalk_username and online_users_cache_for_instance:
                    individual_tt_user_is_online = any(
                        ttstr(tt_user_obj.username) == user_settings.teamtalk_username
                        for tt_user_obj in online_users_cache_for_instance.values()
                    )

                tg.create_task(
                    send_telegram_message(
                        bot_instance=bot_instance_to_use,
                        chat_id=chat_id,
                        session_factory=session_factory,
                        reply_markup=current_reply_markup,
                        tt_user_is_online=individual_tt_user_is_online,
                        settings=settings,
                        cache=cache,
                        text=text,
                    )
                )
    except* TelegramAPIError as eg:
        logger.warning("Some messages failed to send. Total errors: %d", len(eg.exceptions))
        for error in eg.exceptions:
            # The individual error handler is already called inside send_telegram_message_individual
            # So we just log the summary here.
            logger.debug("Failed to send a message (handled individually): %s", error)


def format_telegram_user_display_name(chat: Chat | None) -> str:
    """Formats a Telegram user's display name from a Chat object.

    Returns the Telegram ID as a string if chat object is None or no other info is available.
    """
    if not chat:
        # This function expects a Chat object.
        # If chat is None, we cannot process it to get a display name or ID.
        return "Unknown User"

    # Default to string representation of chat.id if no other name parts are available
    display_name = str(chat.id)

    # Try to construct a more descriptive name
    full_name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
    username_part = f" (@{chat.username})" if chat.username else ""

    if full_name:
        display_name = f"{full_name}{username_part}"
    elif chat.username:  # Only username is available
        display_name = f"@{chat.username}"
    # If neither full_name nor username is present, display_name remains str(chat.id)

    return display_name


async def safe_delete_message(message: Message, log_context_message: str = "message") -> bool:
    """Safely deletes a message, catching TelegramAPIErrors and logging them.

    :param message: The aiogram.types.Message object to delete.
    :param log_context_message: A string to include in the log message for context
                                (e.g., "user settings command", "user menu command").
    :return: True if deletion was successful or if the message was already deleted/not found,
             False if another TelegramAPIError occurred.
    """
    try:
        await message.delete()
    except TelegramBadRequest as e:
        # Specific check for errors indicating the message can't be deleted because it's too old,
        # doesn't exist, or the bot doesn't have rights. These are often not critical failures
        # for the calling function's flow.
        if (
            "message to delete not found" in str(e).lower()
            or "message can't be deleted" in str(e).lower()
            or "message identifier is not specified" in str(e).lower()
        ):  # Should not happen with Message obj
            logger.info(
                "Could not delete %s (message likely already gone or permissions issue): %s", log_context_message, e
            )
            return True  # Treat as "handled" or "not an issue for caller"
        logger.warning("TelegramBadRequest when trying to delete %s: %s", log_context_message, e)
        return False  # Other bad requests might be more problematic
    except TelegramAPIError as e:
        # Catches other errors like Forbidden, etc.
        logger.warning("Could not delete %s due to TelegramAPIError: %s", log_context_message, e)
        return False
    except Exception:
        # Catch any other unexpected error
        logger.exception("Unexpected error when trying to delete %s.", log_context_message)
        return False
    else:
        return True
