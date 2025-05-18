import logging
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk
from pytalk.instance import TeamTalkInstance

from bot.localization import get_text
from bot.core.user_settings import UserSpecificSettings, update_user_settings_in_db
from bot.telegram_bot.filters import IsAdminFilter # For checking admin status on kick/ban
from bot.constants import (
    CALLBACK_ACTION_ID, CALLBACK_ACTION_KICK, CALLBACK_ACTION_BAN,
    CALLBACK_INVALID_DATA, CALLBACK_NO_PERMISSION, CALLBACK_ERROR_FIND_USER_TT,
    CALLBACK_USER_ID_INFO, CALLBACK_USER_KICKED, CALLBACK_USER_BANNED_KICKED,
    CALLBACK_ERROR_ACTION_USER, CALLBACK_ACTION_KICK_GERUND_RU, CALLBACK_ACTION_BAN_GERUND_RU,
    CALLBACK_USER_NOT_FOUND_ANYMORE, CALLBACK_UNKNOWN_ACTION, TT_BOT_NOT_CONNECTED,
    TOGGLE_IGNORE_ERROR_PROCESSING, TOGGLE_IGNORE_ERROR_EMPTY_USERNAME,
    TOGGLE_IGNORE_NOW_IGNORED, TOGGLE_IGNORE_NO_LONGER_IGNORED, TOGGLE_IGNORE_BUTTON_TEXT,
    CALLBACK_NICKNAME_MAX_LENGTH, MUTE_ACTION_MUTE, MUTE_ACTION_UNMUTE
)

logger = logging.getLogger(__name__)
callback_router = Router(name="callback_router")
ttstr = pytalk.instance.sdk.ttstr

# --- User Action Callbacks (ID, Kick, Ban) ---

async def _process_id_action_callback(
    user_id_val: int,
    user_nickname_val: str,
    language: str,
    # tt_instance: TeamTalkInstance | None # Not needed for ID action
) -> str:
    return get_text(CALLBACK_USER_ID_INFO, language, user_nickname=html.quote(user_nickname_val), user_id=user_id_val)

async def _process_kick_action_callback(
    user_id_val: int,
    user_nickname_val: str,
    language: str,
    tt_instance: TeamTalkInstance, # Must be connected
    admin_tg_id: int # For logging
) -> str:
    try:
        user_to_act_on = tt_instance.server.get_user(user_id_val)
        if user_to_act_on:
            user_to_act_on.kick(from_server=True) # PyTalk method
            logger.info(f"Admin {admin_tg_id} kicked TT user {user_nickname_val} ({user_id_val})")
            return get_text(CALLBACK_USER_KICKED, language, user_nickname=html.quote(user_nickname_val))
        return get_text(CALLBACK_USER_NOT_FOUND_ANYMORE, language)
    except Exception as e:
        logger.error(f"Error kicking TT user {user_nickname_val} ({user_id_val}): {e}")
        action_ru = get_text(CALLBACK_ACTION_KICK_GERUND_RU, "ru") # Get Russian gerund for error message
        return get_text(CALLBACK_ERROR_ACTION_USER, language, action="kick", action_ru=action_ru, user_nickname=html.quote(user_nickname_val), error=str(e))

async def _process_ban_action_callback(
    user_id_val: int,
    user_nickname_val: str,
    language: str,
    tt_instance: TeamTalkInstance, # Must be connected
    admin_tg_id: int # For logging
) -> str:
    try:
        user_to_act_on = tt_instance.server.get_user(user_id_val)
        if user_to_act_on:
            user_to_act_on.ban(from_server=True) # PyTalk method
            user_to_act_on.kick(from_server=True) # Ban usually implies kick
            logger.info(f"Admin {admin_tg_id} banned and kicked TT user {user_nickname_val} ({user_id_val})")
            return get_text(CALLBACK_USER_BANNED_KICKED, language, user_nickname=html.quote(user_nickname_val))
        return get_text(CALLBACK_USER_NOT_FOUND_ANYMORE, language)
    except Exception as e:
        logger.error(f"Error banning TT user {user_nickname_val} ({user_id_val}): {e}")
        action_ru = get_text(CALLBACK_ACTION_BAN_GERUND_RU, "ru") # Get Russian gerund
        return get_text(CALLBACK_ERROR_ACTION_USER, language, action="ban", action_ru=action_ru, user_nickname=html.quote(user_nickname_val), error=str(e))


USER_ACTION_CALLBACK_HANDLERS = {
    CALLBACK_ACTION_ID: _process_id_action_callback,
    CALLBACK_ACTION_KICK: _process_kick_action_callback,
    CALLBACK_ACTION_BAN: _process_ban_action_callback,
}

@callback_router.callback_query(F.data.startswith(f"{CALLBACK_ACTION_ID}:") | F.data.startswith(f"{CALLBACK_ACTION_KICK}:") | F.data.startswith(f"{CALLBACK_ACTION_BAN}:"))
async def process_user_action_selection(
    callback_query: CallbackQuery,
    session: AsyncSession, # From DbSessionMiddleware
    language: str, # From UserSettingsMiddleware
    tt_instance: TeamTalkInstance | None # From TeamTalkInstanceMiddleware
):
    await callback_query.answer() # Acknowledge the callback quickly
    if not callback_query.message or not callback_query.from_user: return

    try:
        # Data format: "action:user_id:nickname_prefix"
        action_val, user_id_str_val, user_nickname_val = callback_query.data.split(":", 2)
        user_id_val = int(user_id_str_val)
        # user_nickname_val is the potentially truncated nickname from the button
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data format for user action: {callback_query.data}")
        await callback_query.message.edit_text(get_text(CALLBACK_INVALID_DATA, language))
        return

    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
         await callback_query.message.edit_text(get_text(TT_BOT_NOT_CONNECTED, language))
         return

    reply_text_val = get_text(CALLBACK_UNKNOWN_ACTION, language) # Default
    handler = USER_ACTION_CALLBACK_HANDLERS.get(action_val)

    if handler:
        is_admin_caller = await IsAdminFilter()(callback_query, session) # Check if caller is admin

        if action_val in [CALLBACK_ACTION_KICK, CALLBACK_ACTION_BAN]:
            if not is_admin_caller:
                # Send an answer to the callback, not a new message, for permission errors
                await callback_query.answer(get_text(CALLBACK_NO_PERMISSION, language), show_alert=True)
                # Do not edit the original message if permission denied, or edit to "Permission Denied."
                # await callback_query.message.edit_text(get_text(CALLBACK_NO_PERMISSION, language))
                return
            try:
                # For kick/ban, pass tt_instance and admin_tg_id
                reply_text_val = await handler(user_id_val, user_nickname_val, language, tt_instance, callback_query.from_user.id)
            except Exception as e: # Catch errors from the handler itself
                logger.error(f"Error in {action_val} handler for TT user {user_nickname_val}: {e}")
                reply_text_val = get_text(CALLBACK_ERROR_FIND_USER_TT, language) # Generic error if user not found or other issue
        elif action_val == CALLBACK_ACTION_ID:
            # For ID, tt_instance is not strictly needed by the handler but passed for consistency if ever needed
            reply_text_val = await handler(user_id_val, user_nickname_val, language)
    else:
         logger.warning(f"Unhandled user action '{action_val}' in callback query: {callback_query.data}")

    try:
        await callback_query.message.edit_text(reply_text_val, reply_markup=None) # Clear buttons after action
    except TelegramAPIError as e:
        logger.error(f"Error editing message after user action callback: {e}")


# --- Toggle Ignore User Callback ---

@callback_router.callback_query(F.data.startswith("toggle_ignore_user:"))
async def process_toggle_ignore_user(
    callback_query: CallbackQuery,
    session: AsyncSession, # From DbSessionMiddleware
    language: str, # From UserSettingsMiddleware (language of the user clicking the button)
    user_specific_settings: UserSpecificSettings # Settings of the user clicking
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer(get_text(TOGGLE_IGNORE_ERROR_PROCESSING, language), show_alert=True)
        return

    telegram_id_val = callback_query.from_user.id # TG ID of the user who clicked

    try:
        # Data format: "toggle_ignore_user:tt_username:tt_nickname_prefix"
        _, tt_username_to_toggle_val, nickname_from_callback_val = callback_query.data.split(":", 2)
        tt_username_to_toggle_val = tt_username_to_toggle_val.strip()
        nickname_from_callback_val = nickname_from_callback_val.strip() # This is the display nickname
    except ValueError:
        logger.error(f"Invalid callback data for toggle_ignore_user: {callback_query.data} from user {telegram_id_val}")
        await callback_query.answer(get_text(TOGGLE_IGNORE_ERROR_PROCESSING, language), show_alert=True)
        return

    if not tt_username_to_toggle_val:
        logger.error(f"Empty username in toggle_ignore_user callback: {callback_query.data} from user {telegram_id_val}")
        await callback_query.answer(get_text(TOGGLE_IGNORE_ERROR_EMPTY_USERNAME, language), show_alert=True)
        return

    # Logic based on mute_all_flag:
    # If mute_all_flag is ON, muted_users_set is an "allow list" (exceptions).
    #   - Clicking "ignore" means REMOVE from allow list (effectively mute).
    #   - Clicking "unignore" means ADD to allow list (effectively unmute).
    # If mute_all_flag is OFF, muted_users_set is a "block list".
    #   - Clicking "ignore" means ADD to block list.
    #   - Clicking "unignore" means REMOVE from block list.

    # The button's purpose is to "toggle ignore".
    # "Ignored" means notifications are NOT received for this user.
    is_currently_in_set = tt_username_to_toggle_val in user_specific_settings.muted_users_set

    if user_specific_settings.mute_all_flag: # Mute all is ON (set is allow list)
        if is_currently_in_set: # Was allowed, now toggle to ignore (remove from allow list)
            user_specific_settings.muted_users_set.discard(tt_username_to_toggle_val)
            user_is_now_effectively_ignored_val = True
        else: # Was not allowed (ignored), now toggle to allow (add to allow list)
            user_specific_settings.muted_users_set.add(tt_username_to_toggle_val)
            user_is_now_effectively_ignored_val = False
    else: # Mute all is OFF (set is block list)
        if is_currently_in_set: # Was blocked, now toggle to unblock (remove from block list)
            user_specific_settings.muted_users_set.discard(tt_username_to_toggle_val)
            user_is_now_effectively_ignored_val = False
        else: # Was not blocked, now toggle to block (add to block list)
            user_specific_settings.muted_users_set.add(tt_username_to_toggle_val)
            user_is_now_effectively_ignored_val = True

    await update_user_settings_in_db(session, telegram_id_val, user_specific_settings)

    feedback_key = TOGGLE_IGNORE_NOW_IGNORED if user_is_now_effectively_ignored_val else TOGGLE_IGNORE_NO_LONGER_IGNORED
    feedback_msg_for_answer_val = get_text(feedback_key, language, nickname=html.quote(nickname_from_callback_val))

    # Update the button text/state if needed (though text is static in current implementation)
    # For a dynamic button text (e.g., "Ignore User [Ignored]" vs "Ignore User"), you'd change it here.
    # Current button text is "Toggle ignore status: {nickname}", which doesn't change.
    # We just re-create the same button to ensure the callback data remains consistent if we were to change it.
    button_display_nickname_new_val = html.quote(nickname_from_callback_val) # Already truncated
    button_text_new_val = get_text(TOGGLE_IGNORE_BUTTON_TEXT, language, nickname=button_display_nickname_new_val)
    callback_data_new_val = f"toggle_ignore_user:{tt_username_to_toggle_val}:{nickname_from_callback_val}"

    new_keyboard_val = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_text_new_val, callback_data=callback_data_new_val)]
    ])

    try:
        # Only edit reply markup if it's different, or if you want to confirm the action by re-sending.
        # Since button text is static, this might result in "message is not modified".
        await callback_query.message.edit_reply_markup(reply_markup=new_keyboard_val)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.debug(f"Button markup for {nickname_from_callback_val} was not modified by toggle_ignore.")
        else:
            logger.error(f"TelegramBadRequest editing ignore button for {nickname_from_callback_val}: {e}")
    except TelegramAPIError as e: # Catch other potential API errors
        logger.error(f"TelegramAPIError editing ignore button for {nickname_from_callback_val}: {e}")

    try:
        await callback_query.answer(text=feedback_msg_for_answer_val, show_alert=False) # Subtle feedback
    except TelegramAPIError as e: # If user has already dismissed the message or other issue
        logger.warning(f"Could not send feedback answer for toggle_ignore_user for {nickname_from_callback_val}: {e}")
