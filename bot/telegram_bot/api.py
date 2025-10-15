"""Functions for interacting with the Telegram Bot API."""

import asyncio
from collections.abc import Callable
from gettext import NullTranslations
import logging
from typing import Any

from aiogram import Bot as AiogramBot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.types import InlineKeyboardMarkup, Message
import pytalk
from pytalk.user import User as TeamTalkUser

from bot.constants import DEFAULT_LANGUAGE
from bot.database.engine import AsyncSessionFactoryType
from bot.database.uow import SqlModelUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.notification_service import should_send_silently
from bot.services.subscription_service import SubscriptionService
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
    session_factory: AsyncSessionFactoryType,
    translator_factory: Callable[[str | None], NullTranslations],
    online_users_cache_for_instance: dict[int, TeamTalkUser] | None = None,
    reply_markup_generator: Callable[[str | None, int], InlineKeyboardMarkup | None]
    | None = None,
) -> None:
    """Sends localized messages to recipients and handles errors individually."""
    if not bot_instance_to_use:
        logger.error("No Telegram bot instance provided to broadcast_to_users.")
        return

    tasks = []
    for chat_id, lang_code in recipients_with_lang:
        tasks.append(
            asyncio.create_task(
                _send_and_handle_broadcast_error(
                    bot_instance_to_use=bot_instance_to_use,
                    chat_id=chat_id,
                    lang_code=lang_code,
                    text_generator=text_generator,
                    cache=cache,
                    session_factory=session_factory,
                    translator_factory=translator_factory,
                    online_users_cache_for_instance=online_users_cache_for_instance,
                    reply_markup_generator=reply_markup_generator,
                )
            )
        )

    if tasks:
        await asyncio.gather(*tasks)


async def _send_and_handle_broadcast_error(
    bot_instance_to_use: AiogramBot,
    chat_id: int,
    lang_code: str | None,
    text_generator: Callable[[str | None], str],
    cache: CacheService,
    session_factory: AsyncSessionFactoryType,
    translator_factory: Callable[[str | None], NullTranslations],
    online_users_cache_for_instance: dict[int, TeamTalkUser] | None,
    reply_markup_generator: Callable[[str | None, int], InlineKeyboardMarkup | None]
    | None,
) -> None:
    """Helper coroutine to send a message and handle Forbidden error."""
    try:
        language_code = lang_code or DEFAULT_LANGUAGE
        text = text_generator(language_code)
        current_reply_markup = (
            reply_markup_generator(language_code, chat_id)
            if reply_markup_generator
            else None
        )

        send_silently = await should_send_silently(
            chat_id, cache, online_users_cache_for_instance
        )

        await send_telegram_message(
            bot_instance=bot_instance_to_use,
            chat_id=chat_id,
            reply_markup=current_reply_markup,
            disable_notification=send_silently,
            text=text,
        )
    except TelegramForbiddenError:
        logger.warning(
            "User %s blocked the bot or is deactivated. Deleting all user data...",
            chat_id,
        )
        # Use a default translator for the deletion process logs/messages
        default_translator = translator_factory(DEFAULT_LANGUAGE)
        async with SqlModelUnitOfWork(session_factory) as uow:
            subscription_service = SubscriptionService(uow, cache)
            await subscription_service.delete_profile(chat_id, default_translator)
            await uow.commit()
    except Exception:
        logger.exception(
            "An unexpected error occurred during broadcast to chat_id %s.", chat_id
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
