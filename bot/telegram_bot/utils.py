import logging
import asyncio
import pytalk
from typing import Callable
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message, CallbackQuery
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError, TelegramBadRequest
from sqlalchemy.exc import SQLAlchemyError

from bot.config import app_config
from bot.services import user_service
from bot.database.engine import SessionFactory
from bot.core.user_settings import USER_SETTINGS_CACHE
from bot.state import ONLINE_USERS_CACHE
from bot.constants import (
    DEFAULT_LANGUAGE,
)
from bot.telegram_bot.bot_instances import tg_bot_event, tg_bot_message

ttstr = pytalk.instance.sdk.ttstr
logger = logging.getLogger(__name__)


async def _handle_telegram_api_error(error: TelegramAPIError, chat_id: int):
    """
    Handles specific Telegram API errors, performing actions like unsubscribing users
    or logging detailed error information.
    """
    if isinstance(error, TelegramForbiddenError):
        if "bot was blocked by the user" in str(error).lower() or "user is deactivated" in str(error).lower():
            logger.warning(f"User {chat_id} blocked the bot or is deactivated. Deleting all user data...")
            try:
                async with SessionFactory() as session:
                    success = await user_service.delete_full_user_profile(session, chat_id)
                if success:
                    logger.info(f"Successfully deleted all data for blocked/deactivated user {chat_id} (using user_service).")
                else:
                    logger.error(f"Failed to delete data for blocked/deactivated user {chat_id}, though an attempt was made.")
            except SQLAlchemyError as db_err:
                logger.error(f"Failed to delete data for blocked/deactivated user {chat_id} from DB: {db_err}")
        else:
            logger.error(f"Telegram API Forbidden error for chat_id {chat_id}: {error}")

    elif isinstance(error, TelegramBadRequest):
        if "chat not found" in str(error).lower():
            logger.warning(f"Chat not found for TG ID {chat_id}. Assuming user is gone. Deleting all user data. Error: {error}")
            try:
                async with SessionFactory() as session:
                    delete_success = await user_service.delete_full_user_profile(session, chat_id)
                if delete_success:
                    logger.info(f"Successfully deleted all data for TG ID {chat_id} due to chat not found (using user_service).")
                else:
                    logger.error(f"Failed to delete all data for TG ID {chat_id} after chat not found.")

                if USER_SETTINGS_CACHE.pop(chat_id, None): # Remove from cache regardless
                    logger.debug(f"Removed user {chat_id} from settings cache after chat not found.")
                else:
                    logger.debug(f"User {chat_id} was not in settings cache (or already removed) after chat not found.")
            except SQLAlchemyError as db_cleanup_err:
                logger.error(f"Exception during full data cleanup for TG ID {chat_id} (chat not found): {db_cleanup_err}")
        else:
            logger.error(f"Telegram API BadRequest (non 'chat not found') for chat_id {chat_id}: {error}")

    elif isinstance(error, TelegramAPIError): # Catch-all for other TelegramAPIError types
        logger.error(f"Unhandled Telegram API error for chat_id {chat_id}: {error}")

    # Non-TelegramAPIError exceptions are not handled by this function.
    # The calling function would need a separate except block for those if desired.


def _should_send_silently(chat_id: int, tt_user_is_online: bool) -> bool:
    """
    Checks if a message to a given chat_id should be sent silently based on
    NOON settings and the provided online status of their linked TeamTalk user.
    """
    recipient_settings = USER_SETTINGS_CACHE.get(chat_id)

    if (
        recipient_settings and
        recipient_settings.not_on_online_enabled and
        recipient_settings.not_on_online_confirmed and
        tt_user_is_online # Directly use the passed boolean
    ):
        logger.debug(f"Message to {chat_id} will be silent: linked user is online and NOON is enabled.")
        return True

    return False


async def send_telegram_message_individual(
    bot_instance: Bot,
    chat_id: int,
    language: str = DEFAULT_LANGUAGE,
    reply_markup: InlineKeyboardMarkup | None = None,
    tt_user_is_online: bool = False,
    **kwargs
) -> bool:
    send_silently = _should_send_silently(chat_id, tt_user_is_online)

    try:
        await bot_instance.send_message(
            chat_id=chat_id,
            reply_markup=reply_markup,
            disable_notification=send_silently,
            **kwargs # Pass kwargs directly
        )
        logger.debug(f"Message sent to {chat_id}. Silent: {send_silently}, kwargs used: {kwargs}")
        return True

    except TelegramAPIError as e:
        await _handle_telegram_api_error(e, chat_id)
        return False

    # Non-TelegramAPIError exceptions will propagate if not caught by the caller.
    # If they were to be caught here and also result in 'False', an outer try-except would be needed.
    # Based on current structure, only TelegramAPIError results in False from this function.


async def send_telegram_messages_to_list(
    bot_instance_to_use: Bot,
    chat_ids: list[int],
    text_generator: Callable[[str], str], # Takes language code, returns text
    reply_markup_generator: Callable[[str, int], InlineKeyboardMarkup | None] | None = None
):
    """
    Sends messages to a list of chat_ids.
    Uses the provided bot_instance_to_use.
    """
    if not bot_instance_to_use:
        logger.error("No Telegram bot instance provided to send_telegram_messages_to_list.")
        return

    online_tt_usernames = {ttstr(user.username) for user in ONLINE_USERS_CACHE.values()}
    tasks_list = []
    for chat_id in chat_ids:
        user_settings = USER_SETTINGS_CACHE.get(chat_id)
        # user_settings.language_code is already a string. DEFAULT_LANGUAGE is also a string code.
        language_code = user_settings.language_code if user_settings else DEFAULT_LANGUAGE
        text = text_generator(language_code)

        current_reply_markup = None
        if reply_markup_generator:
            current_reply_markup = reply_markup_generator(
                language,
                chat_id
            )

        individual_tt_user_is_online = False
        if user_settings and user_settings.teamtalk_username:
            if user_settings.teamtalk_username in online_tt_usernames:
                individual_tt_user_is_online = True

        tasks_list.append(send_telegram_message_individual(
            bot_instance=bot_instance_to_use,
            chat_id=chat_id,
            language=language_code,
            reply_markup=current_reply_markup,
            tt_user_is_online=individual_tt_user_is_online,
            text=text,
            parse_mode="HTML"
        ))
    await asyncio.gather(*tasks_list)


async def send_or_edit_paginated_list(
    target: "Message | CallbackQuery", # type: ignore
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    bot: Bot | None = None, # Required if target is Message, for reply
    **kwargs
) -> None:
    """
    Sends a new message or edits an existing one with paginated content.

    :param target: The aiogram Message or CallbackQuery object.
    :param text: The text content for the message.
    :param reply_markup: The InlineKeyboardMarkup for the message.
    :param bot: The Bot instance, required if target is a Message.
    :param kwargs: Additional arguments to pass to send_message or edit_message_text.
    """
    answered_with_alert = False
    if hasattr(target, 'message') and target.message: # Handles CallbackQuery
        try:
            await target.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                **kwargs
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                logger.debug(f"Message not modified for chat_id {target.message.chat.id}, skipping edit.")
                # Try to answer the callback query to remove the "loading" state
                if hasattr(target, 'answer'):
                    try:
                        await target.answer()
                    except Exception as answer_e: # Could be already answered
                        logger.warning(f"Failed to answer CbQ after 'message not modified': {answer_e}")
            else: # Other TelegramBadRequest
                logger.error(f"Error editing message for chat_id {target.message.chat.id}: {e}", exc_info=True)
                if hasattr(target, 'answer'):
                    try:
                        await target.answer("Error updating list.", show_alert=True) # type: ignore
                        answered_with_alert = True
                    except Exception as answer_e:
                        logger.warning(f"Failed to answer CbQ with alert after edit error: {answer_e}")
        except Exception as e: # Other errors during edit
            logger.error(f"Generic error editing message for chat_id {target.message.chat.id}: {e}", exc_info=True)
            if hasattr(target, 'answer'):
                try:
                    await target.answer("Error updating list.", show_alert=True) # type: ignore
                    answered_with_alert = True
                except Exception as answer_e:
                    logger.warning(f"Failed to answer CbQ with alert after generic edit error: {answer_e}")

    elif hasattr(target, 'reply') and bot: # Handles Message
        if target: # Ensure target (Message object) is not None
            try:
                await target.reply(
                    text=text,
                    reply_markup=reply_markup,
                    **kwargs
                )
            except Exception as e: # Catch potential errors during reply
                logger.error(f"Error replying to message for chat_id {target.chat.id}: {e}", exc_info=True)
        else:
            logger.error("Attempted to reply to a None message object.")

    else:
        logger.error(
            "Invalid target type for send_or_edit_paginated_list. "
            "Must be Message or CallbackQuery. If Message, bot instance must be provided."
        )

    # If it's a CbQ and edit was successful (or not modified) and we haven't shown an alert
    if hasattr(target, 'answer') and not answered_with_alert:
        try:
            # This might fail if already answered by the "message not modified" block, which is fine.
            await target.answer() # type: ignore
        except TelegramAPIError as e:
            cbq_id = target.id if hasattr(target, 'id') else 'N/A'
            if "query is too old" in str(e).lower() or "query id is invalid" in str(e).lower():
                logger.debug(f"CbQ {cbq_id} likely already answered or too old.")
            else:
                logger.warning(f"Failed to answer CbQ {cbq_id} at the end of send_or_edit: {e}")
        except Exception as e:
            cbq_id = target.id if hasattr(target, 'id') else 'N/A'
            logger.warning(f"Generic error answering CbQ {cbq_id} at the end of send_or_edit: {e}")