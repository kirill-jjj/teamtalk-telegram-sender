import logging
import asyncio
from typing import Callable
from aiogram import Bot, html
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError, TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder

import pytalk # For TeamTalkUser, TeamTalkInstance type hints
from pytalk.instance import TeamTalkInstance

from bot.config import app_config
from bot.localization import get_text
from bot.database.crud import remove_subscriber, delete_user_data_fully
from bot.database.engine import SessionFactory # For direct session usage if needed
from bot.core.user_settings import USER_SETTINGS_CACHE
from bot.constants import (
    DEFAULT_LANGUAGE,
    CALLBACK_NICKNAME_MAX_LENGTH,
)
from bot.telegram_bot.bot_instances import tg_bot_event, tg_bot_message # Import bot instances
from bot.core.utils import get_tt_user_display_name

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


async def _handle_telegram_api_error(error: TelegramAPIError, chat_id: int, language: str): # language may be unused
    """
    Handles specific Telegram API errors, performing actions like unsubscribing users
    or logging detailed error information.
    """
    if isinstance(error, TelegramForbiddenError):
        if "bot was blocked by the user" in str(error).lower() or "user is deactivated" in str(error).lower():
            logger.warning(f"User {chat_id} blocked the bot or is deactivated. Unsubscribing...")
            try:
                async with SessionFactory() as unsubscribe_session:
                    removed = await remove_subscriber(unsubscribe_session, chat_id)
                if removed:
                    logger.info(f"Successfully unsubscribed blocked/deactivated user {chat_id}.")
                else:
                    logger.info(f"User {chat_id} was likely already unsubscribed or not found (remove_subscriber returned False).")
                USER_SETTINGS_CACHE.pop(chat_id, None)
                logger.info(f"Removed user {chat_id} from settings cache.")
            except Exception as db_err:
                logger.error(f"Failed to unsubscribe blocked/deactivated user {chat_id} from DB: {db_err}")
        else:
            # For other Forbidden errors, just log. reply_tt_method was removed.
            logger.error(f"Telegram API Forbidden error for chat_id {chat_id}: {error}")

    elif isinstance(error, TelegramBadRequest):
        if "chat not found" in str(error).lower():
            logger.warning(f"Chat not found for TG ID {chat_id}. Assuming user is gone. Deleting all user data. Error: {error}")
            try:
                async with SessionFactory() as session:
                    delete_success = await delete_user_data_fully(session, chat_id)
                if delete_success:
                    logger.info(f"Successfully deleted all data for TG ID {chat_id} due to chat not found.")
                else:
                    logger.error(f"Failed to delete all data for TG ID {chat_id} after chat not found.")

                if USER_SETTINGS_CACHE.pop(chat_id, None): # Remove from cache regardless
                    logger.info(f"Removed user {chat_id} from settings cache after chat not found.")
                else:
                    logger.info(f"User {chat_id} was not in settings cache (or already removed) after chat not found.")
            except Exception as db_cleanup_err:
                logger.error(f"Exception during full data cleanup for TG ID {chat_id} (chat not found): {db_cleanup_err}")
        else:
            # For other BadRequest errors, just log. reply_tt_method was removed.
            logger.error(f"Telegram API BadRequest (non 'chat not found') for chat_id {chat_id}: {error}")

    elif isinstance(error, TelegramAPIError): # Catch-all for other TelegramAPIError types
        logger.error(f"Unhandled Telegram API error for chat_id {chat_id}: {error}")

    # Non-TelegramAPIError exceptions are not handled by this function.
    # The calling function would need a separate except block for those if desired.


async def _should_send_silently(chat_id: int, tt_instance_for_check: TeamTalkInstance | None) -> bool:
    """
    Checks if a message to a given chat_id should be sent silently based on
    NOON (Notification On Online) settings and the online status of their linked TeamTalk user.
    """
    should_be_silent = False
    recipient_settings = USER_SETTINGS_CACHE.get(chat_id)

    if recipient_settings and \
       recipient_settings.not_on_online_enabled and \
       recipient_settings.not_on_online_confirmed and \
       recipient_settings.teamtalk_username and \
       tt_instance_for_check:

        tt_username_to_check = recipient_settings.teamtalk_username
        try:
            is_tt_user_online = False
            if tt_instance_for_check.connected and tt_instance_for_check.logged_in:
                all_online_users = tt_instance_for_check.server.get_users()
                for online_user in all_online_users:
                    if ttstr(online_user.username) == tt_username_to_check:
                        is_tt_user_online = True
                        break
            else:
                logger.warning(f"Cannot check TT status for {tt_username_to_check}, TT instance not ready for chat_id {chat_id} (in _should_send_silently).")

            if is_tt_user_online:
                should_be_silent = True
                logger.info(f"Message to {chat_id} should be silent as their linked TT user '{tt_username_to_check}' is online.")
        except Exception as e:
            logger.warning(f"Could not check TeamTalk status for user '{tt_username_to_check}' (TG ID: {chat_id}) in _should_send_silently: {e}")
            # Keep should_be_silent as False in case of error

    return should_be_silent


async def send_telegram_message_individual(
    bot_instance: Bot,
    chat_id: int,
    text: str,
    language: str = DEFAULT_LANGUAGE,
    reply_markup: InlineKeyboardMarkup | None = None,
    tt_instance_for_check: TeamTalkInstance | None = None
    # reply_tt_method: Callable | None = None, # Parameter removed
) -> bool: # Return type bool is already present, ensuring it stays.
    # Determine if the message should be sent silently using the helper function
    send_silently = await _should_send_silently(chat_id, tt_instance_for_check)

    try:
        await bot_instance.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_notification=send_silently
        )
        logger.debug(f"Message sent to {chat_id}. Silent: {send_silently}")
        return True # Message sent successfully

    except TelegramAPIError as e:
        # Delegate Telegram API error handling to the new helper function
        await _handle_telegram_api_error(e, chat_id, language)
        return False # Message sending failed

    # Non-TelegramAPIError exceptions will propagate if not caught by the caller.
    # If they were to be caught here and also result in 'False', an outer try-except would be needed.
    # Based on current structure, only TelegramAPIError results in False from this function.


async def send_telegram_messages_to_list(
    bot_token_to_use: str, # TG_EVENT_TOKEN or TG_BOT_MESSAGE_TOKEN
    chat_ids: list[int],
    text_generator: Callable[[str], str], # Takes language code, returns text
    reply_markup_generator: Callable[[str, str, str, int], InlineKeyboardMarkup | None] | None = None, # tt_username, tt_nickname, lang, recipient_tg_id
    tt_user_username_for_markup: str | None = None,
    tt_user_nickname_for_markup: str | None = None,
    tt_instance_for_check: TeamTalkInstance | None = None # For silent notification check
):
    """
    Sends messages to a list of chat_ids.
    Uses the appropriate bot instance based on bot_token_to_use.
    """
    bot_to_use = tg_bot_event if bot_token_to_use == app_config["TG_EVENT_TOKEN"] else tg_bot_message
    if not bot_to_use:
        logger.error(f"No Telegram bot instance available for token: {bot_token_to_use}")
        return

    tasks_list = []
    for chat_id_val in chat_ids:
        user_settings_val = USER_SETTINGS_CACHE.get(chat_id_val)
        language_val = user_settings_val.language if user_settings_val else DEFAULT_LANGUAGE
        text_val = text_generator(language_val)

        current_reply_markup_val = None
        if reply_markup_generator and tt_user_username_for_markup and tt_user_nickname_for_markup:
            current_reply_markup_val = reply_markup_generator(
                tt_user_username_for_markup,
                tt_user_nickname_for_markup,
                language_val,
                chat_id_val
            )

        tasks_list.append(send_telegram_message_individual(
            bot_instance=bot_to_use,
            chat_id=chat_id_val,
            text=text_val,
            language=language_val,
            reply_markup=current_reply_markup_val,
            tt_instance_for_check=tt_instance_for_check
        ))
    await asyncio.gather(*tasks_list)


async def show_user_buttons(
    message: Message,
    command_type: str, # e.g., "id", "kick", "ban"
    language: str,
    tt_instance: TeamTalkInstance | None
):
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await message.reply(get_text("TT_BOT_NOT_CONNECTED", language))
        return

    try:
        users_list = tt_instance.server.get_users()
    except Exception as e:
        logger.error(f"Failed to get users from TT for {command_type} button list: {e}")
        await message.reply(get_text("TT_ERROR_GETTING_USERS", language))
        return

    if not users_list:
        await message.reply(get_text("SHOW_USERS_NO_USERS_ONLINE", language))
        return

    builder = InlineKeyboardBuilder()
    my_user_id_val = tt_instance.getMyUserID()
    users_added_to_list = 0

    for user_obj in users_list:
        if user_obj.id == my_user_id_val: # Don't show self
            continue

        # Use new helper for user display name for button text
        user_nickname_val = get_tt_user_display_name(user_obj, language)
        # Keep original logic for callback_nickname_val to ensure it's short and not localized
        callback_nickname_val = (ttstr(user_obj.nickname) or ttstr(user_obj.username) or "unknown")[:CALLBACK_NICKNAME_MAX_LENGTH]

        builder.button(
            text=html.quote(user_nickname_val), # Display full nickname (now from helper)
            callback_data=f"{command_type}:{user_obj.id}:{callback_nickname_val}" # Use truncated for callback
        )
        users_added_to_list +=1

    if users_added_to_list == 0: # No other users online
         await message.reply(get_text("SHOW_USERS_NO_OTHER_USERS_ONLINE", language))
         return

    builder.adjust(2) # Adjust to 2 buttons per row

    command_text_key_map = {
        # "id" action removed
        "kick": "SHOW_USERS_SELECT_KICK",
        "ban": "SHOW_USERS_SELECT_BAN"
    }
    command_text_key = command_text_key_map.get(command_type, "SHOW_USERS_SELECT_DEFAULT")
    await message.reply(get_text(command_text_key, language), reply_markup=builder.as_markup())
    