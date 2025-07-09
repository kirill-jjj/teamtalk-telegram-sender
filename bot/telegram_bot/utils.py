"""Utility functions for Telegram bot operations, like sending messages and handling API errors."""

import asyncio
from collections.abc import Callable
import logging

# For type hinting Services
from typing import TYPE_CHECKING, Any  # Added Any

from aiogram import Bot as AiogramBot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message
import pytalk
from pytalk.user import User as TeamTalkUser
from sqlalchemy.exc import SQLAlchemyError

from bot.constants import (
    DEFAULT_LANGUAGE,
)
from bot.services import notification_service, user_service

if TYPE_CHECKING:
    from bot.models import UserSettings
    from bot.services_container import Services

ttstr = pytalk.instance.sdk.ttstr
logger = logging.getLogger(__name__)


async def _handle_telegram_api_error(  # noqa: PLR0912
    error: TelegramAPIError, chat_id: int, services: "Services"
) -> None:
    """Handles specific Telegram API errors."""
    if not services:
        logger.error(
            "Telegram API error for chat_id %s but services context was missing for full cleanup: %s",
            chat_id,
            error,
        )
        return

    if isinstance(error, TelegramForbiddenError):
        if "bot was blocked by the user" in str(error).lower() or "user is deactivated" in str(error).lower():
            logger.warning("User %s blocked the bot or is deactivated. Deleting all user data...", chat_id)
            try:
                async with services.session_factory() as session:
                    success = await user_service.delete_full_user_profile(session, chat_id, services=services)
                if success:
                    logger.info("Successfully deleted all data for blocked/deactivated user %s.", chat_id)
                else:
                    logger.error(
                        "Failed to delete data for blocked/deactivated user %s, though an attempt was made.", chat_id
                    )
            except SQLAlchemyError:
                logger.exception("Failed to delete data for blocked/deactivated user %s from DB.", chat_id)
        else:
            logger.error("Telegram API Forbidden error for chat_id %s: %s", chat_id, error)

    elif isinstance(error, TelegramBadRequest):
        if "chat not found" in str(error).lower():
            logger.warning(
                "Chat not found for TG ID %s. Assuming user is gone. Deleting all user data. Error: %s",
                chat_id,
                error,
            )
            try:
                async with services.session_factory() as session:
                    delete_success = await user_service.delete_full_user_profile(session, chat_id, services=services)
                if delete_success:
                    logger.info("Successfully deleted all data for TG ID %s due to chat not found.", chat_id)
                else:
                    logger.error("Failed to delete all data for TG ID %s after chat not found.", chat_id)
            except SQLAlchemyError:
                logger.exception(
                    "Exception during full data cleanup for TG ID %s (chat not found).",
                    chat_id,
                )
        else:
            logger.error("Telegram API BadRequest (non 'chat not found') for chat_id %s: %s", chat_id, error)

    elif isinstance(error, TelegramAPIError):
        logger.error("Unhandled Telegram API error for chat_id %s: %s", chat_id, error)


def _should_send_silently(chat_id: int, *, tt_user_is_online: bool, services: "Services") -> bool:
    """Checks if a message to a given chat_id should be sent silently.

    This is based on NOON settings and the provided online status of their linked TeamTalk user.
    Uses `services.cache.get_user_settings()` and `notification_service`.
    """
    recipient_settings = services.cache.get_user_settings(chat_id)

    if notification_service.is_user_subject_to_noon_check(recipient_settings) and tt_user_is_online:
        logger.debug(
            "Message to %s will be silent: linked user is online and NOON is subject to check "
            "(via notification_service).",
            chat_id,
        )
        return True

    return False


async def send_telegram_message_individual(
    bot_instance: AiogramBot,
    chat_id: int,
    services: "Services",
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    tt_user_is_online: bool = False,
    **kwargs: Any,  # noqa: ANN401
) -> bool:
    """Sends a single Telegram message to a user, handling potential errors.

    Args:
        bot_instance: The Aiogram Bot instance to use for sending.
        chat_id: The Telegram chat ID to send the message to.
        services: The application's services container.
        _language: The language code for localization (currently unused here, but kept for consistency).
        reply_markup: Optional InlineKeyboardMarkup for the message.
        tt_user_is_online: Whether the user's linked TeamTalk account is currently online.
        **kwargs: Additional arguments to pass to `bot_instance.send_message`.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    send_silently = _should_send_silently(chat_id=chat_id, tt_user_is_online=tt_user_is_online, services=services)

    try:
        await bot_instance.send_message(
            chat_id=chat_id, reply_markup=reply_markup, disable_notification=send_silently, **kwargs
        )
        logger.debug("Message sent to %s. Silent: %s, kwargs used: %s", chat_id, send_silently, kwargs)
    except TelegramAPIError as e:
        await _handle_telegram_api_error(e, chat_id, services=services)
        return False
    else:
        return True


async def send_telegram_messages_to_list(
    bot_instance_to_use: AiogramBot,
    chat_ids: list[int],
    text_generator: Callable[[str], str],
    services: "Services",
    online_users_cache_for_instance: dict[int, TeamTalkUser] | None = None,
    reply_markup_generator: Callable[[str, int], InlineKeyboardMarkup | None] | None = None,
) -> None:
    """Sends localized messages to a list of Telegram chat IDs.

    Args:
        bot_instance_to_use: The Aiogram Bot instance for sending messages.
        chat_ids: A list of Telegram chat IDs to send messages to.
        text_generator: A callable that takes a language code and returns the message text.
        services: The application's services container.
        online_users_cache_for_instance: Optional cache of online TeamTalk users for NOON check.
        reply_markup_generator: Optional callable that takes lang_code and chat_id
                                and returns an InlineKeyboardMarkup.
    """
    if not bot_instance_to_use:
        logger.error("No Telegram bot instance provided to send_telegram_messages_to_list.")
        return

    tasks_list = []
    for chat_id in chat_ids:
        user_settings: UserSettings | None = services.cache.get_user_settings(chat_id)
        language_code = user_settings.language_code if user_settings else DEFAULT_LANGUAGE
        text = text_generator(language_code)
        current_reply_markup = reply_markup_generator(language_code, chat_id) if reply_markup_generator else None

        individual_tt_user_is_online = False
        if user_settings and user_settings.teamtalk_username and online_users_cache_for_instance:
            for tt_user_obj in online_users_cache_for_instance.values():
                if ttstr(tt_user_obj.username) == user_settings.teamtalk_username:
                    individual_tt_user_is_online = True
                    break

        tasks_list.append(
            send_telegram_message_individual(
                bot_instance=bot_instance_to_use,
                chat_id=chat_id,
                reply_markup=current_reply_markup,
                tt_user_is_online=individual_tt_user_is_online,
                services=services,
                text=text,
            )
        )
    await asyncio.gather(*tasks_list)


async def send_or_edit_paginated_list(  # noqa: PLR0912, PLR0915
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    bot: AiogramBot | None = None,
    **kwargs: Any,  # noqa: ANN401
) -> None:
    """Sends a new message or edits an existing one with paginated content.

    :param target: The aiogram Message or CallbackQuery object.
    :param text: The text content for the message.
    :param reply_markup: The InlineKeyboardMarkup for the message.
    :param bot: The Bot instance, required if target is a Message.
    :param kwargs: Additional arguments to pass to send_message or edit_message_text.
    """
    answered_with_alert = False
    if isinstance(target, CallbackQuery) and target.message:  # Handles CallbackQuery
        if hasattr(target.message, "edit_text"): # Check if message is not InaccessibleMessage
            try:
                await target.message.edit_text(text=text, reply_markup=reply_markup, **kwargs)
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    logger.debug("Message not modified for chat_id %s, skipping edit. Error: %s", target.message.chat.id, e)
                    # Try to answer the callback query to remove the "loading" state
                    try:
                        await target.answer() # type: ignore[call-arg]
                    except Exception as answer_e:  # Could be already answered
                        logger.warning("Failed to answer CbQ after 'message not modified': %s", answer_e)
                else:  # Other TelegramBadRequest
                    logger.exception("Error editing message for chat_id %s.", target.message.chat.id)
                    try:
                        await target.answer("Error updating list.", show_alert=True)
                        answered_with_alert = True
                    except Exception as answer_e:
                        logger.warning("Failed to answer CbQ with alert after edit error: %s", answer_e)
            except Exception:  # Other errors during edit
                logger.exception("Generic error editing message for chat_id %s.", target.message.chat.id)
                try:
                    await target.answer("Error updating list.", show_alert=True)
                    answered_with_alert = True
                except Exception as answer_e:
                    logger.warning("Failed to answer CbQ with alert after generic edit error: %s", answer_e)
        else:
            logger.warning("Cannot edit InaccessibleMessage in chat_id %s.", target.message.chat.id)


    elif isinstance(target, Message) and bot:  # Handles Message
        if target:  # Ensure target (Message object) is not None
            try:
                await target.reply(text=text, reply_markup=reply_markup, **kwargs)
            except Exception:  # Catch potential errors during reply
                logger.exception("Error replying to message for chat_id %s.", target.chat.id)
        else:
            logger.error("Attempted to reply to a None message object.")

    else:
        logger.error(
            "Invalid target type for send_or_edit_paginated_list. "
            "Must be Message or CallbackQuery. If Message, bot instance must be provided."
        )

    if isinstance(target, CallbackQuery) and not answered_with_alert:
        try:
            # This might fail if already answered by the "message not modified" block, which is fine.
            await target.answer() # type: ignore[call-arg]
        except TelegramAPIError as e:
            cbq_id = target.id if hasattr(target, "id") else "N/A"
            if "query is too old" in str(e).lower() or "query id is invalid" in str(e).lower():
                logger.debug("CbQ %s likely already answered or too old.", cbq_id)
            else:
                logger.warning("Failed to answer CbQ %s at the end of send_or_edit: %s", cbq_id, e)
        except Exception as e:
            cbq_id = target.id if hasattr(target, "id") else "N/A"
            logger.warning("Generic error answering CbQ %s at the end of send_or_edit: %s", cbq_id, e)


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
