"""Functions for interacting with the Telegram Bot API."""

import asyncio
from collections.abc import Callable
import logging
from typing import Any

from aiogram import Bot as AiogramBot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
)
from aiogram.types import (
    Chat,
    InlineKeyboardMarkup,
    Message,
)
import pytalk
from pytalk.user import User as TeamTalkUser

from bot.constants import (
    DEFAULT_LANGUAGE,
)
from bot.services import notification_service
from bot.services.cache_service import CacheService
from bot.telegram_bot.formatters import format_telegram_user_display_name

ttstr = pytalk.instance.sdk.ttstr
logger = logging.getLogger(__name__)


def _should_send_silently(
    chat_id: int, *, tt_user_is_online: bool, cache: CacheService
) -> bool:
    """Checks if a message to a given chat_id should be sent silently."""
    recipient_settings = cache.get_user_settings(chat_id)

    if (
        notification_service.is_user_subject_to_noon_check(recipient_settings)
        and tt_user_is_online
    ):
        logger.debug(
            "Message to %s will be silent: linked user is online and NOON is "
            "subject to check (via notification_service).",
            chat_id,
        )
        return True

    return False


async def send_telegram_message(
    bot_instance: AiogramBot,
    chat_id: int,
    cache: CacheService,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    tt_user_is_online: bool = False,
    **kwargs: Any,
) -> bool:
    """Sends a single Telegram message, logs errors, and returns success status."""
    send_silently = _should_send_silently(
        chat_id=chat_id, tt_user_is_online=tt_user_is_online, cache=cache
    )
    try:
        await bot_instance.send_message(
            chat_id=chat_id,
            reply_markup=reply_markup,
            disable_notification=send_silently,
            **kwargs,
        )
        logger.debug(
            "Message sent to %s. Silent: %s, kwargs used: %s",
            chat_id,
            send_silently,
            kwargs,
        )
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

    chat_info_tasks: dict[int, asyncio.Task[Chat]] = {}
    try:
        async with asyncio.TaskGroup() as tg:
            for user_id in ids:
                task: asyncio.Task[Chat] = tg.create_task(bot.get_chat(user_id))
                chat_info_tasks[user_id] = task
    except* TelegramAPIError as eg:
        for error in eg.exceptions:
            # The specific user ID isn't easily available from the exception group,
            # so we log a general warning. The logic below will handle individual
            # failures.
            logger.warning("Could not fetch chat info for at least one user: %s", error)

    display_names: dict[int, str] = {}
    for user_id, task in chat_info_tasks.items():
        if task.done() and not task.cancelled() and not task.exception():
            chat_result = task.result()
            display_names[user_id] = format_telegram_user_display_name(chat_result)
        else:
            if task.exception():
                logger.error(
                    "Failed to get chat info for TG ID %s due to an exception: %s",
                    user_id,
                    task.exception(),
                )
            # Fallback to the ID itself if fetching failed for any reason
            display_names[user_id] = str(user_id)

    return display_names


async def get_display_name_for_id(bot: AiogramBot, user_id: int) -> str:
    """Safely fetches the display name for a single user ID."""
    try:
        chat_info = await bot.get_chat(user_id)
        return format_telegram_user_display_name(chat_info)
    except TelegramAPIError:
        logger.warning("Could not fetch chat info for user %s", user_id)
        return str(user_id)


async def broadcast_to_users(
    bot_instance_to_use: AiogramBot,
    recipients_with_lang: list[tuple[int, str | None]],
    text_generator: Callable[[str | None], str],
    cache: CacheService,
    online_users_cache_for_instance: dict[int, TeamTalkUser] | None = None,
    reply_markup_generator: Callable[[str | None, int], InlineKeyboardMarkup | None]
    | None = None,
) -> None:
    """Send localized messages to a list of recipients using a TaskGroup."""
    if not bot_instance_to_use:
        logger.error("No Telegram bot instance provided to broadcast_to_users.")
        return

    async with asyncio.TaskGroup() as tg:
        for chat_id, lang_code in recipients_with_lang:
            language_code = lang_code or DEFAULT_LANGUAGE
            text = text_generator(language_code)
            current_reply_markup = (
                reply_markup_generator(language_code, chat_id)
                if reply_markup_generator
                else None
            )

            individual_tt_user_is_online = False
            if online_users_cache_for_instance:
                individual_tt_user_is_online = (
                    await notification_service.is_linked_user_online(
                        chat_id, cache, online_users_cache_for_instance
                    )
                )

            tg.create_task(
                send_telegram_message(
                    bot_instance=bot_instance_to_use,
                    chat_id=chat_id,
                    reply_markup=current_reply_markup,
                    tt_user_is_online=individual_tt_user_is_online,
                    cache=cache,
                    text=text,
                )
            )


async def safe_delete_message(
    message: Message, log_context_message: str = "message"
) -> bool:
    """Safely deletes a message, catching TelegramAPIErrors and logging them.

    :param message: The aiogram.types.Message object to delete.
    :param log_context_message: A string to include in the log message for context
                                (e.g., "user settings command", "user menu command").
    :return: True if deletion was successful or if the message was already
        deleted/not found, False if another TelegramAPIError occurred.
    """
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
    except Exception:
        # Catch any other unexpected error
        logger.exception(
            "Unexpected error when trying to delete %s.", log_context_message
        )
        return False
    else:
        return True
