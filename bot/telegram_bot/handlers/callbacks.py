import logging
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
import math # For pagination

import pytalk
from pytalk.instance import TeamTalkInstance

from bot.localization import get_text
from bot.core.user_settings import UserSpecificSettings, update_user_settings_in_db
from bot.telegram_bot.filters import IsAdminFilter # For checking admin status on kick/ban
from bot.constants import (
    CALLBACK_ACTION_KICK, CALLBACK_ACTION_BAN,
    CALLBACK_NICKNAME_MAX_LENGTH, MUTE_ACTION_MUTE, MUTE_ACTION_UNMUTE,
    USERS_PER_PAGE # Import the new constant
)

logger = logging.getLogger(__name__)
callback_router = Router(name="callback_router")
ttstr = pytalk.instance.sdk.ttstr

# --- User Action Callbacks (ID, Kick, Ban) ---

# _process_id_action_callback removed as it's no longer used.

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
            return get_text("CALLBACK_USER_KICKED", language, user_nickname=html.quote(user_nickname_val))
        return get_text(CALLBACK_USER_NOT_FOUND_ANYMORE, language)
    except Exception as e:
        logger.error(f"Error kicking TT user {user_nickname_val} ({user_id_val}): {e}")
        action_ru = get_text("CALLBACK_ACTION_KICK_GERUND_RU", "ru") # Get Russian gerund for error message
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
            return get_text("CALLBACK_USER_BANNED_KICKED", language, user_nickname=html.quote(user_nickname_val))
        return get_text("CALLBACK_USER_NOT_FOUND_ANYMORE", language)
    except Exception as e:
        logger.error(f"Error banning TT user {user_nickname_val} ({user_id_val}): {e}")
        action_ru = get_text("CALLBACK_ACTION_BAN_GERUND_RU", "ru") # Get Russian gerund
        return get_text(CALLBACK_ERROR_ACTION_USER, language, action="ban", action_ru=action_ru, user_nickname=html.quote(user_nickname_val), error=str(e))


USER_ACTION_CALLBACK_HANDLERS = {
    # CALLBACK_ACTION_ID entry removed
    CALLBACK_ACTION_KICK: _process_kick_action_callback,
    CALLBACK_ACTION_BAN: _process_ban_action_callback,
}

@callback_router.callback_query(F.data.startswith(f"{CALLBACK_ACTION_KICK}:") | F.data.startswith(f"{CALLBACK_ACTION_BAN}:")) # Removed ID
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
        await callback_query.message.edit_text(get_text("CALLBACK_INVALID_DATA", language))
        return

    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
         await callback_query.message.edit_text(get_text("TT_BOT_NOT_CONNECTED", language))
         return

    reply_text_val = get_text("CALLBACK_UNKNOWN_ACTION", language) # Default
    handler = USER_ACTION_CALLBACK_HANDLERS.get(action_val)

    if handler:
        is_admin_caller = await IsAdminFilter()(callback_query, session) # Check if caller is admin

        if action_val in [CALLBACK_ACTION_KICK, CALLBACK_ACTION_BAN]:
            if not is_admin_caller:
                # Send an answer to the callback, not a new message, for permission errors
                await callback_query.answer(get_text("CALLBACK_NO_PERMISSION", language), show_alert=True)
                return
            try:
                # For kick/ban, pass tt_instance and admin_tg_id
                reply_text_val = await handler(user_id_val, user_nickname_val, language, tt_instance, callback_query.from_user.id)
            except Exception as e: # Catch errors from the handler itself
                logger.error(f"Error in {action_val} handler for TT user {user_nickname_val}: {e}")
                reply_text_val = get_text("CALLBACK_ERROR_FIND_USER_TT", language) # Generic error if user not found or other issue
    else:
         logger.warning(f"Unhandled user action '{action_val}' in callback query: {callback_query.data}")

    try:
        await callback_query.message.edit_text(reply_text_val, reply_markup=None) # Clear buttons after action
    except TelegramAPIError as e:
        logger.error(f"Error editing message after user action callback: {e}")




# --- Settings Callbacks ---

from bot.telegram_bot.callback_data import ( # Import all new factories
    SettingsCallback,
    LanguageCallback,
    SubscriptionCallback,
    NotificationActionCallback,
    MuteAllCallback,
    UserListCallback,
    PaginateUsersCallback,
    ToggleMuteSpecificCallback
)

@callback_router.callback_query(SettingsCallback.filter(F.action == "language"))
async def cq_show_language_menu( # Renamed for clarity
    callback_query: CallbackQuery,
    # session: AsyncSession, # Not directly used here, but available if needed
    language: str, # Current language from UserSettingsMiddleware
    # user_specific_settings: UserSpecificSettings # Not directly used here
    callback_data: SettingsCallback # Consumes the SettingsCallback
):
    if not callback_query.message: # Should not happen
        await callback_query.answer("Error: No message associated with callback.")
        return
    await callback_query.answer() # Acknowledge

    # Create language selection buttons
    eng_button = InlineKeyboardButton(
        text="English (US)",
        callback_data=LanguageCallback(action="set_lang", lang_code="en").pack()
    )
    rus_button = InlineKeyboardButton(
        text="Русский (RU)",
        callback_data=LanguageCallback(action="set_lang", lang_code="ru").pack()
    )
    # Back button to main settings
    back_button = InlineKeyboardButton(
        text=get_text("BACK_TO_SETTINGS_BTN", language), # Assuming this key exists or create one like "Back to Main Menu"
        callback_data=SettingsCallback(action="back_to_main").pack()
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [eng_button],
        [rus_button],
        [back_button]
    ])

    try:
        await callback_query.message.edit_text(
            text=get_text("CHOOSE_LANGUAGE_PROMPT", language),
            reply_markup=keyboard
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for language selection: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for language selection: {e}")

# Consolidated handler for setting language
@callback_router.callback_query(LanguageCallback.filter(F.action == "set_lang"))
async def cq_set_language(
    callback_query: CallbackQuery,
    session: AsyncSession,
    user_specific_settings: UserSpecificSettings,
    callback_data: LanguageCallback # Consumes LanguageCallback
):
    if not callback_query.message or not callback_query.from_user or not callback_data.lang_code:
        await callback_query.answer("Error: Missing data for language update.")
        return

    new_lang_code = callback_data.lang_code
    original_lang_code = user_specific_settings.language
    user_specific_settings.language = new_lang_code

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_specific_settings)
    except Exception as e:
        logger.error(f"Failed to update language in DB for user {callback_query.from_user.id} to {new_lang_code}: {e}")
        user_specific_settings.language = original_lang_code
        await callback_query.answer(get_text("error_occurred", new_lang_code), show_alert=True)
        return

    # After setting language, go back to the main settings menu, now in the new language
    # This requires re-creating the main settings menu
    main_settings_buttons = [
        [InlineKeyboardButton(
            text=get_text("SETTINGS_BTN_LANGUAGE", new_lang_code),
            callback_data=SettingsCallback(action="language").pack()
        )],
        [InlineKeyboardButton(
            text=get_text("SETTINGS_BTN_SUBSCRIPTIONS", new_lang_code),
            callback_data=SettingsCallback(action="subscriptions").pack()
        )],
        [InlineKeyboardButton(
            text=get_text("SETTINGS_BTN_NOTIFICATIONS", new_lang_code),
            callback_data=SettingsCallback(action="notifications").pack()
        )]
    ]
    main_settings_keyboard = InlineKeyboardMarkup(inline_keyboard=main_settings_buttons)
    main_settings_text = get_text("SETTINGS_MENU_HEADER", new_lang_code)

    try:
        await callback_query.message.edit_text(
            text=main_settings_text,
            reply_markup=main_settings_keyboard
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message to show updated settings menu in {new_lang_code}: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message to show updated settings menu in {new_lang_code}: {e}")

    lang_name_display = get_text(f"LANGUAGE_BTN_{new_lang_code.upper()}", new_lang_code)
    try:
        await callback_query.answer(
            get_text("LANGUAGE_UPDATED_TO", new_lang_code, lang_name=lang_name_display),
            show_alert=False
        )
    except TelegramAPIError as e:
         logger.warning(f"Could not send language update confirmation for {new_lang_code}: {e}")


# --- Subscription Settings Callbacks ---

from bot.database.models import NotificationSetting # Added import

# Helper to create subscription settings keyboard (Refactored)
def _create_subscription_settings_keyboard(
    language: str,
    current_setting: NotificationSetting # Enum member
) -> InlineKeyboardMarkup:
    active_marker = get_text("ACTIVE_CHOICE_MARKER", language)

    # Map NotificationSetting enum to (text_key, callback_value)
    settings_map = {
        NotificationSetting.ALL: ("SUBS_SETTING_ALL_BTN", "all"),
        NotificationSetting.LEAVE_OFF: ("SUBS_SETTING_JOIN_ONLY_BTN", "leave_off"), # Join only = Leave events OFF
        NotificationSetting.JOIN_OFF: ("SUBS_SETTING_LEAVE_ONLY_BTN", "join_off"),   # Leave only = Join events OFF
        NotificationSetting.NONE: ("SUBS_SETTING_NONE_BTN", "none"),
    }

    keyboard_buttons = []
    for setting_enum, (text_key, val_str) in settings_map.items():
        prefix = active_marker if current_setting == setting_enum else ""
        button_text = f"{prefix}{get_text(text_key, language)}"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=SubscriptionCallback(action="set_sub", setting_value=val_str).pack()
            )
        ])

    keyboard_buttons.append([
        InlineKeyboardButton(
            text=get_text("BACK_TO_SETTINGS_BTN", language),
            callback_data=SettingsCallback(action="back_to_main").pack()
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

# Renamed: cq_settings_subscriptions now cq_show_subscriptions_menu
@callback_router.callback_query(SettingsCallback.filter(F.action == "subscriptions"))
async def cq_show_subscriptions_menu( # Renamed for clarity
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: SettingsCallback # Consumes SettingsCallback
):
    if not callback_query.message:
        await callback_query.answer("Error: No message.")
        return
    await callback_query.answer()

    current_notification_setting = user_specific_settings.notification_settings
    keyboard = _create_subscription_settings_keyboard(language, current_notification_setting)

    try:
        await callback_query.message.edit_text(
            text=get_text("SUBS_SETTINGS_MENU_HEADER", language),
            reply_markup=keyboard
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for subscription settings menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for subscription settings menu: {e}")

# Consolidated handler for setting subscription type
@callback_router.callback_query(SubscriptionCallback.filter(F.action == "set_sub"))
async def cq_set_subscription_setting(
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str, # Current language, not new one yet
    user_specific_settings: UserSpecificSettings,
    callback_data: SubscriptionCallback
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer("Error: Missing data.")
        return

    # Map callback_data.setting_value (string) back to NotificationSetting enum
    value_to_enum_map = {
        "all": NotificationSetting.ALL,
        "leave_off": NotificationSetting.LEAVE_OFF, # Join Only
        "join_off": NotificationSetting.JOIN_OFF,   # Leave Only
        "none": NotificationSetting.NONE,
    }
    new_setting_enum = value_to_enum_map.get(callback_data.setting_value)

    # Find text key for confirmation (this is a bit clunky, direct mapping might be better)
    setting_to_text_key = {
        NotificationSetting.ALL: "SUBS_SETTING_ALL_BTN",
        NotificationSetting.LEAVE_OFF: "SUBS_SETTING_JOIN_ONLY_BTN",
        NotificationSetting.JOIN_OFF: "SUBS_SETTING_LEAVE_ONLY_BTN",
        NotificationSetting.NONE: "SUBS_SETTING_NONE_BTN",
    }
    setting_text_key = setting_to_text_key.get(new_setting_enum, "unknown_setting")


    if new_setting_enum is None:
        logger.error(f"Invalid subscription setting value: {callback_data.setting_value}")
        await callback_query.answer("Error: Invalid setting value.", show_alert=True)
        return

    original_setting = user_specific_settings.notification_settings
    user_specific_settings.notification_settings = new_setting_enum

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_specific_settings)
    except Exception as e:
        logger.error(f"Failed to update subscription setting in DB for user {callback_query.from_user.id} to {new_setting_enum.name}: {e}")
        user_specific_settings.notification_settings = original_setting # Revert
        await callback_query.answer(get_text("error_occurred", language), show_alert=True)
        return

    updated_keyboard = _create_subscription_settings_keyboard(language, new_setting_enum)
    try:
        await callback_query.message.edit_text(
            text=get_text("SUBS_SETTINGS_MENU_HEADER", language), # Header remains the same
            reply_markup=updated_keyboard
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest re-editing message for subscription settings menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError re-editing message for subscription settings menu: {e}")

    setting_display_name = get_text(setting_text_key, language)
    try:
        await callback_query.answer(
            get_text("SUBS_SETTING_UPDATED_TO", language, setting_name=setting_display_name),
            show_alert=False
        )
    except TelegramAPIError as e:
        logger.warning(f"Could not send subscription update confirmation for {new_setting_enum.name}: {e}")

# This handler now manages returns to the main settings menu
@callback_router.callback_query(SettingsCallback.filter(F.action == "back_to_main"))
async def cq_back_to_main_settings_menu( # Renamed for clarity
    callback_query: CallbackQuery,
    language: str, # From UserSettingsMiddleware
    callback_data: SettingsCallback # Consumes the callback
):
    if not callback_query.message:
        await callback_query.answer("Error: No message.")
        return
    await callback_query.answer() # Acknowledge

    # Re-create main settings menu using SettingsCallback for buttons
    main_settings_buttons = [
        [InlineKeyboardButton(
            text=get_text("SETTINGS_BTN_LANGUAGE", language),
            callback_data=SettingsCallback(action="language").pack() # Leads to cq_show_language_menu
        )],
        [InlineKeyboardButton(
            text=get_text("SETTINGS_BTN_SUBSCRIPTIONS", language),
            callback_data=SettingsCallback(action="subscriptions").pack() # Leads to cq_show_subscriptions_menu
        )],
        [InlineKeyboardButton(
            text=get_text("SETTINGS_BTN_NOTIFICATIONS", language),
            callback_data=SettingsCallback(action="notifications").pack() # Leads to cq_show_notifications_menu (defined below)
        )]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=main_settings_buttons)

    try:
        await callback_query.message.edit_text(
            text=get_text("SETTINGS_MENU_HEADER", language),
            reply_markup=keyboard
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for back_to_main_settings_menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for back_to_main_settings_menu: {e}")


# --- Notification Settings Callbacks ---

# Refactored _create_notification_settings_keyboard
def _create_notification_settings_keyboard( # Renamed for clarity if needed, but name is ok
    language: str,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardMarkup:
    is_noon_enabled = user_specific_settings.not_on_online_enabled
    # is_noon_confirmed is assumed true due to SubscriptionCheckMiddleware
    status_text = get_text("ENABLED_STATUS" if is_noon_enabled else "DISABLED_STATUS", language)
    noon_button_text = get_text("NOTIF_SETTING_NOON_BTN_TOGGLE", language, status=status_text)

    noon_button = InlineKeyboardButton(
        text=noon_button_text,
        callback_data=NotificationActionCallback(action="toggle_noon").pack()
    )
    manage_muted_button = InlineKeyboardButton(
        text=get_text("NOTIF_SETTING_MANAGE_MUTED_BTN", language),
        callback_data=NotificationActionCallback(action="manage_muted").pack()
    )
    back_button = InlineKeyboardButton(
        text=get_text("BACK_TO_SETTINGS_BTN", language),
        callback_data=SettingsCallback(action="back_to_main").pack()
    )
    return InlineKeyboardMarkup(inline_keyboard=[[noon_button], [manage_muted_button], [back_button]])

# Renamed: cq_settings_notifications now cq_show_notifications_menu
@callback_router.callback_query(SettingsCallback.filter(F.action == "notifications"))
async def cq_show_notifications_menu( # Renamed for clarity
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: SettingsCallback # Consumes SettingsCallback
):
    if not callback_query.message:
        await callback_query.answer("Error: No message.")
        return
    await callback_query.answer()
    keyboard = _create_notification_settings_keyboard(language, user_specific_settings)
    try:
        await callback_query.message.edit_text(
            text=get_text("NOTIF_SETTINGS_MENU_HEADER", language),
            reply_markup=keyboard
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for notification settings menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for notification settings menu: {e}")

# Refactored cq_toggle_noon_setting
@callback_router.callback_query(NotificationActionCallback.filter(F.action == "toggle_noon"))
async def cq_toggle_noon_setting_action( # Renamed for clarity
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: NotificationActionCallback # Consumes NotificationActionCallback
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer("Error: Missing data.")
        return


    await callback_query.answer() # Acknowledge action
    user_specific_settings.not_on_online_enabled = not user_specific_settings.not_on_online_enabled

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_specific_settings)
    except Exception as e:
        logger.error(f"Failed to update NOON setting in DB for user {callback_query.from_user.id}: {e}")
        user_specific_settings.not_on_online_enabled = not user_specific_settings.not_on_online_enabled
        try:
            await callback_query.answer(get_text("error_occurred", language), show_alert=True)
        except TelegramAPIError as e_ans:
             logger.warning(f"Could not send error alert for NOON toggle DB fail: {e_ans}")
        return

    new_status_text = get_text("ENABLED_STATUS" if user_specific_settings.not_on_online_enabled else "DISABLED_STATUS", language)
    try:
        # Send toast first, then update keyboard
        await callback_query.answer(
            get_text("NOTIF_SETTING_NOON_UPDATED_TO", language, status=new_status_text),
            show_alert=False
        )
    except TelegramAPIError as e:
        logger.warning(f"Could not send NOON update confirmation toast: {e}")

    updated_keyboard = _create_notification_settings_keyboard(language, user_specific_settings)
    try:
        await callback_query.message.edit_text(
            text=get_text("NOTIF_SETTINGS_MENU_HEADER", language),
            reply_markup=updated_keyboard
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest re-editing message for NOON toggle: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError re-editing message for NOON toggle: {e}")


# --- Manage Muted Users Callbacks ---

# Refactored _create_manage_muted_users_keyboard
def _create_manage_muted_users_keyboard(
    language: str,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardMarkup:
    is_mute_all_enabled = user_specific_settings.mute_all_flag
    mute_all_status_text = get_text("ENABLED_STATUS" if is_mute_all_enabled else "DISABLED_STATUS", language)
    mute_all_button_text = get_text("MUTE_ALL_BTN_TOGGLE", language, status=mute_all_status_text)
    mute_all_button = InlineKeyboardButton(
        text=mute_all_button_text,
        callback_data=MuteAllCallback(action="toggle_mute_all").pack()
    )

    if is_mute_all_enabled:
        list_users_button_text = get_text("LIST_ALLOWED_USERS_BTN", language)
        list_users_cb_data = UserListCallback(action="list_allowed").pack()
    else:
        list_users_button_text = get_text("LIST_MUTED_USERS_BTN", language)
        list_users_cb_data = UserListCallback(action="list_muted").pack()
    list_users_button = InlineKeyboardButton(text=list_users_button_text, callback_data=list_users_cb_data)

    mute_from_server_list_button = InlineKeyboardButton(
        text=get_text("MUTE_FROM_SERVER_LIST_BTN", language),
        callback_data=UserListCallback(action="list_all_accounts").pack() # Changed action
    )
    back_to_notif_settings_button = InlineKeyboardButton(
        text=get_text("BACK_TO_NOTIF_SETTINGS_BTN", language),
        callback_data=SettingsCallback(action="notifications").pack()
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [mute_all_button], [list_users_button], [mute_from_server_list_button], [back_to_notif_settings_button]
    ])

# Renamed: cq_manage_muted_users now cq_show_manage_muted_menu
@callback_router.callback_query(NotificationActionCallback.filter(F.action == "manage_muted"))
async def cq_show_manage_muted_menu( # Renamed for clarity
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: NotificationActionCallback # Consumes
):
    if not callback_query.message:
        await callback_query.answer("Error: No message.")
        return
    await callback_query.answer()
    keyboard = _create_manage_muted_users_keyboard(language, user_specific_settings)
    try:
        await callback_query.message.edit_text(
            text=get_text("MANAGE_MUTED_MENU_HEADER", language),
            reply_markup=keyboard
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for manage_muted_users menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for manage_muted_users menu: {e}")

# Refactored cq_toggle_mute_all_setting
@callback_router.callback_query(MuteAllCallback.filter(F.action == "toggle_mute_all"))
async def cq_toggle_mute_all_action( # Renamed for clarity
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: MuteAllCallback # Consumes
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer("Error: Missing data.")
        return

    await callback_query.answer() # Acknowledge first

    user_specific_settings.mute_all_flag = not user_specific_settings.mute_all_flag

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_specific_settings)
    except Exception as e:
        logger.error(f"Failed to update mute_all_flag in DB for user {callback_query.from_user.id}: {e}")
        user_specific_settings.mute_all_flag = not user_specific_settings.mute_all_flag # Revert
        try:
            await callback_query.answer(get_text("error_occurred", language), show_alert=True)
        except TelegramAPIError as e_ans:
            logger.warning(f"Could not send error alert for mute_all_flag DB fail: {e_ans}")
        return

    # Send confirmation toast
    new_status_text = get_text("ENABLED_STATUS" if user_specific_settings.mute_all_flag else "DISABLED_STATUS", language)
    try:
        await callback_query.answer(
            get_text("MUTE_ALL_UPDATED_TO", language, status=new_status_text),
            show_alert=False
        )
    except TelegramAPIError as e:
        logger.warning(f"Could not send mute_all_flag update confirmation toast: {e}")

    # Re-display the menu with updated button text
    updated_keyboard = _create_manage_muted_users_keyboard(language, user_specific_settings)
    try:
        await callback_query.message.edit_text(
            text=get_text("MANAGE_MUTED_MENU_HEADER", language),
            reply_markup=updated_keyboard
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest re-editing message for toggle_mute_all_action: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError re-editing message for toggle_mute_all_action: {e}")

# --- Paginated User List for Muted/Allowed Users (Refactored) ---

# USERS_PER_PAGE is now imported from bot.constants

# _create_paginated_user_list_keyboard (Refactored)
def _create_paginated_user_list_keyboard(
    language: str,
    page_users: list[str],
    current_page: int,
    total_pages: int,
    list_type: str,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardMarkup:
    keyboard_rows = []
    for idx, username in enumerate(page_users):
        button_text_key = "UNMUTE_USER_BTN" if list_type == "muted" else "MUTE_USER_BTN"
        button_text = get_text(button_text_key, language, username=username)
        # Nickname is not available here directly, pass username as nickname for ToggleMuteSpecificCallback if it's optional
        # Or, if nickname is essential for toast, it implies ToggleMuteSpecificCallback for these lists might not need it,
        # or these lists should perhaps also deal with User objects if available.
        # For now, assuming nickname in ToggleMuteSpecificCallback is optional or can be username.
        callback_d = ToggleMuteSpecificCallback(
            action="toggle_user", # Kept action for clarity, can be removed if prefix is unique enough
            user_idx=idx,
            current_page=current_page,
            list_type=list_type
        ).pack()
        keyboard_rows.append([InlineKeyboardButton(text=button_text, callback_data=callback_d)])

    pagination_row = []
    if current_page > 0:
        pagination_row.append(InlineKeyboardButton(
            text=get_text("PAGINATION_PREV_BTN", language),
            callback_data=PaginateUsersCallback(list_type=list_type, page=current_page - 1).pack()
        ))
    if current_page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(
            text=get_text("PAGINATION_NEXT_BTN", language),
            callback_data=PaginateUsersCallback(list_type=list_type, page=current_page + 1).pack()
        ))
    if pagination_row:
        keyboard_rows.append(pagination_row)

    keyboard_rows.append([InlineKeyboardButton(
        text=get_text("BACK_TO_MANAGE_MUTED_BTN", language),
        callback_data=NotificationActionCallback(action="manage_muted").pack()
    )])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

# _display_paginated_user_list (Minor changes for clarity, logic mostly same)
async def _display_paginated_user_list(
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    list_type: str,
    page: int = 0
):
    if not callback_query.message: return
    # await callback_query.answer() # Answered by callers or specific toggle handler

    users_to_list_set = user_specific_settings.muted_users_set
    # is_mute_all = user_specific_settings.mute_all_flag # Not directly used for header logic anymore, list_type implies it

    if list_type == "muted":
        header_text = get_text("MUTED_USERS_LIST_HEADER", language)
        empty_list_message = get_text("NO_MUTED_USERS_FOUND", language)
    elif list_type == "allowed":
        header_text = get_text("ALLOWED_USERS_LIST_HEADER", language)
        empty_list_message = get_text("NO_ALLOWED_USERS_FOUND", language)
    else:
        logger.error(f"Invalid list_type '{list_type}' in _display_paginated_user_list")
        await callback_query.message.edit_text("Error: Invalid list type.")
        return

    sorted_users = sorted(list(users_to_list_set))
    total_users = len(sorted_users)
    total_pages = math.ceil(total_users / USERS_PER_PAGE) if total_users > 0 else 1 # USERS_PER_PAGE used
    page = max(0, min(page, total_pages - 1))

    start_index = page * USERS_PER_PAGE # USERS_PER_PAGE used
    end_index = start_index + USERS_PER_PAGE # USERS_PER_PAGE used
    page_users_slice = sorted_users[start_index:end_index]

    message_parts = [header_text]
    if not sorted_users:
        message_parts.append(empty_list_message)
    else:
        for i, username in enumerate(page_users_slice, start=start_index + 1):
            message_parts.append(f"{i}. {html.quote(username)}")

    page_indicator_text = get_text("PAGE_INDICATOR", language, current_page=page + 1, total_pages=total_pages)
    message_parts.append(f"\n{page_indicator_text}")
    final_message_text = "\n".join(message_parts)

    keyboard = _create_paginated_user_list_keyboard(
        language, page_users_slice, page, total_pages, list_type, user_specific_settings
    )
    try:
        await callback_query.message.edit_text(text=final_message_text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for paginated user list ({list_type}, page {page}): {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for paginated user list ({list_type}, page {page}): {e}")

# Consolidated handler for listing muted/allowed users
@callback_router.callback_query(UserListCallback.filter(F.action.in_(["list_muted", "list_allowed"])))
async def cq_list_internal_users( # Renamed for clarity
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: UserListCallback
):
    await callback_query.answer() # Acknowledge this initial call
    list_type = "muted" if callback_data.action == "list_muted" else "allowed"

    # Consistency check
    is_mute_all = user_specific_settings.mute_all_flag
    if (list_type == "muted" and is_mute_all) or \
       (list_type == "allowed" and not is_mute_all):
        alert_message = "Mute All is ON, showing Allowed list." if is_mute_all else "Mute All is OFF, showing Muted list."
        logger.warning(f"User {callback_query.from_user.id} triggered {callback_data.action} with inconsistent mute_all_flag ({is_mute_all}). Correcting list_type.")
        await callback_query.answer(f"Inconsistency: {alert_message}", show_alert=True)
        list_type = "allowed" if is_mute_all else "muted"

    await _display_paginated_user_list(callback_query, language, user_specific_settings, list_type, 0)


@callback_router.callback_query(PaginateUsersCallback.filter(F.list_type.in_(["muted", "allowed"])))
async def cq_paginate_internal_user_list( # Renamed for clarity
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: PaginateUsersCallback
):
    # _display_paginated_user_list will .answer()
    await _display_paginated_user_list(
        callback_query, language, user_specific_settings, callback_data.list_type, callback_data.page
    )


# --- Mute/Unmute from Server Account List Callbacks (Refactored from server user list) ---

# Renamed from _create_server_user_list_keyboard
def _create_account_list_keyboard(
    language: str,
    page_accounts: list[pytalk.UserAccount], # Now takes list of UserAccount objects
    current_page: int,
    total_pages: int,
    user_specific_settings: UserSpecificSettings
) -> InlineKeyboardMarkup:
    keyboard_rows = []
    # Enumerate to get index for user_idx
    for idx, account_obj in enumerate(page_accounts):
        username_str = ttstr(account_obj._account.szUsername)
        display_name = username_str

        is_in_set = username_str in user_specific_settings.muted_users_set
        is_effectively_muted = (user_specific_settings.mute_all_flag and not is_in_set) or \
                               (not user_specific_settings.mute_all_flag and is_in_set)

        current_status_text = get_text("MUTED_STATUS" if is_effectively_muted else "NOT_MUTED_STATUS", language)
        # Button text still uses username for display
        button_text = get_text("TOGGLE_MUTE_STATUS_BTN", language, username=display_name, current_status=current_status_text)

        callback_d = ToggleMuteSpecificCallback(
            action="toggle_user",
            user_idx=idx,  # Use index instead of username/nickname
            current_page=current_page,
            list_type="all_accounts"
        ).pack()
        keyboard_rows.append([InlineKeyboardButton(text=button_text, callback_data=callback_d)])

    pagination_row = []
    if current_page > 0:
        pagination_row.append(InlineKeyboardButton(
            text=get_text("PAGINATION_PREV_BTN", language),
            callback_data=PaginateUsersCallback(list_type="all_accounts", page=current_page - 1).pack()
        ))
    if current_page < total_pages - 1:
        pagination_row.append(InlineKeyboardButton(
            text=get_text("PAGINATION_NEXT_BTN", language),
            callback_data=PaginateUsersCallback(list_type="all_accounts", page=current_page + 1).pack()
        ))
    if pagination_row:
        keyboard_rows.append(pagination_row)

    keyboard_rows.append([InlineKeyboardButton(
        text=get_text("BACK_TO_MANAGE_MUTED_BTN", language),
        callback_data=NotificationActionCallback(action="manage_muted").pack()
    )])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

# Renamed from _display_server_user_list
async def _display_account_list(
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance,
    page: int = 0
):
    if not callback_query.message: return
    # await callback_query.answer() # Answered by callers or specific toggle handler

    try:
        # Fetch all user accounts
        all_accounts_tt = await tt_instance.list_user_accounts()
    except Exception as e:
        logger.error(f"Failed to get user accounts from TT: {e}")
        await callback_query.message.edit_text(get_text("tt_error_getting_users", language)) # Can reuse or make specific
        return

    # Sort accounts by username (case-insensitive)
    sorted_accounts_tt = sorted(
        all_accounts_tt,
        key=lambda acc: ttstr(acc._account.szUsername).lower() # Access underlying SDK struct
    )

    total_accounts = len(sorted_accounts_tt)
    total_pages = math.ceil(total_accounts / USERS_PER_PAGE) if total_accounts > 0 else 1 # USERS_PER_PAGE used
    page = max(0, min(page, total_pages - 1)) # Ensure page is valid

    start_index = page * USERS_PER_PAGE # USERS_PER_PAGE used
    end_index = start_index + USERS_PER_PAGE # USERS_PER_PAGE used
    page_accounts_slice = sorted_accounts_tt[start_index:end_index]

    message_parts = [get_text("ALL_ACCOUNTS_LIST_HEADER", language)] # New header key
    if not sorted_accounts_tt:
        message_parts.append(get_text("NO_SERVER_ACCOUNTS_FOUND", language)) # New empty list key

    page_indicator_text = get_text("PAGE_INDICATOR", language, current_page=page + 1, total_pages=total_pages)
    message_parts.append(f"\n{page_indicator_text}")
    final_message_text = "\n".join(message_parts)

    keyboard = _create_account_list_keyboard( # Call renamed keyboard func
        language, page_accounts_slice, page, total_pages, user_specific_settings
    )
    try:
        await callback_query.message.edit_text(text=final_message_text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"Error editing message for account list (page {page}): {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for account list (page {page}): {e}")

@callback_router.callback_query(UserListCallback.filter(F.action == "list_all_accounts"))
async def cq_show_all_accounts_list( # Renamed
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance | None,
    callback_data: UserListCallback
):
    await callback_query.answer()
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in: # Ensure tt_instance is valid
        await callback_query.answer(get_text("TT_BOT_NOT_CONNECTED_FOR_LIST", language), show_alert=True)
        return
    await _display_account_list(callback_query, language, user_specific_settings, tt_instance, 0)

@callback_router.callback_query(PaginateUsersCallback.filter(F.list_type == "all_accounts"))
async def cq_paginate_all_accounts_list_action( # Renamed
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance | None,
    callback_data: PaginateUsersCallback
):
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in: # Ensure tt_instance is valid
        await callback_query.answer(get_text("TT_BOT_NOT_CONNECTED_FOR_LIST", language), show_alert=True)
        return
    await _display_account_list( # Call renamed display func
        callback_query, language, user_specific_settings, tt_instance, callback_data.page
    )

# Consolidated handler for toggling mute status (from any list type)
@callback_router.callback_query(ToggleMuteSpecificCallback.filter(F.action == "toggle_user"))
async def cq_toggle_specific_user_mute_action( # Renamed
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance | None, # Needed if list_type is "server_users" for refresh
    callback_data: ToggleMuteSpecificCallback
):
    if not callback_query.message or not callback_query.from_user: return

    user_idx = callback_data.user_idx
    current_page = callback_data.current_page
    list_type = callback_data.list_type

    username_to_toggle: str | None = None
    display_nickname_for_toast: str | None = None # For toast messages

    # Retrieve the actual username based on list_type and user_idx
    if list_type == "all_accounts":
        if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
            await callback_query.answer(get_text("TT_BOT_NOT_CONNECTED_FOR_LIST", language), show_alert=True)
            return
        try:
            all_accounts_tt = await tt_instance.list_user_accounts()
            # Ensure sorting is identical to how it was displayed
            sorted_accounts = sorted(all_accounts_tt, key=lambda acc: ttstr(acc._account.szUsername).lower())

            start_index = current_page * USERS_PER_PAGE
            current_page_items = sorted_accounts[start_index : start_index + USERS_PER_PAGE]

            if 0 <= user_idx < len(current_page_items):
                target_account = current_page_items[user_idx]
                username_to_toggle = ttstr(target_account._account.szUsername)
                display_nickname_for_toast = username_to_toggle # UserAccount has no separate nickname
            else:
                logger.warning(f"Invalid user_idx {user_idx} for all_accounts list page {current_page}.")
        except Exception as e:
            logger.error(f"Error retrieving account for toggle: {e}")
            await callback_query.answer(get_text("error_occurred", language), show_alert=True)
            return

    elif list_type in ["muted", "allowed"]:
        relevant_set = user_specific_settings.muted_users_set
        sorted_list_usernames = sorted(list(relevant_set))

        start_index = current_page * USERS_PER_PAGE
        current_page_items = sorted_list_usernames[start_index : start_index + USERS_PER_PAGE]

        if 0 <= user_idx < len(current_page_items):
            username_to_toggle = current_page_items[user_idx]
            display_nickname_for_toast = username_to_toggle # Nickname is username for these lists
        else:
            logger.warning(f"Invalid user_idx {user_idx} for {list_type} list page {current_page}.")
    else:
        logger.error(f"Unknown list_type '{list_type}' in cq_toggle_specific_user_mute_action.")
        await callback_query.answer("Error: Unknown list type.", show_alert=True)
        return

    if not username_to_toggle or not display_nickname_for_toast:
        logger.error(f"Could not determine username for toggle. user_idx: {user_idx}, list_type: {list_type}, page: {current_page}")
        await callback_query.answer(get_text("error_occurred", language), show_alert=True)
        if list_type == "all_accounts" and tt_instance and tt_instance.connected:
             await _display_account_list(callback_query, language, user_specific_settings, tt_instance, 0) # Refresh to page 0
        elif list_type in ["muted", "allowed"]:
             await _display_paginated_user_list(callback_query, language, user_specific_settings, list_type, 0) # Refresh to page 0
        return

    # Toggle logic
    if username_to_toggle in user_specific_settings.muted_users_set:
        user_specific_settings.muted_users_set.discard(username_to_toggle)
    else:
        user_specific_settings.muted_users_set.add(username_to_toggle)

    is_mute_all_active = user_specific_settings.mute_all_flag
    effectively_muted_after_toggle = (is_mute_all_active and username_to_toggle not in user_specific_settings.muted_users_set) or \
                                     (not is_mute_all_active and username_to_toggle in user_specific_settings.muted_users_set)

    status_for_toast = get_text("MUTED_STATUS" if effectively_muted_after_toggle else "NOT_MUTED_STATUS", language)

    toast_message = get_text("USER_MUTE_STATUS_UPDATED_TOAST", language, username=html.quote(display_nickname_for_toast), status=status_for_toast)
    if list_type == "muted" or list_type == "allowed": # Specific toasts for these lists if needed
         toast_message = get_text("USER_MUTED_TOAST" if effectively_muted_after_toggle else "USER_UNMUTED_TOAST", language, username=html.quote(display_nickname_for_toast))

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_specific_settings)
        await callback_query.answer(toast_message, show_alert=False)
    except Exception as e:
        logger.error(f"DB error or answer error in toggle_user for {username_to_toggle}: {e}")
        # Revert change in memory on DB fail
        if username_to_toggle in user_specific_settings.muted_users_set:
            user_specific_settings.muted_users_set.discard(username_to_toggle)
        else:
            user_specific_settings.muted_users_set.add(username_to_toggle)
        try:
            await callback_query.answer(get_text("error_occurred", language), show_alert=True)
        except TelegramAPIError: pass # Ignore if can't send error toast
        # Do not refresh list if DB failed, as it would show inconsistent state
        return

    # Refresh the correct list to the same page
    if list_type == "all_accounts":
        if tt_instance and tt_instance.connected: # Ensure tt_instance is still valid
            await _display_account_list(callback_query, language, user_specific_settings, tt_instance, current_page)
        else: # If TT disconnected, cannot refresh the server list, show error or go back
            await callback_query.answer(get_text("TT_BOT_NOT_CONNECTED_FOR_LIST", language), show_alert=True)
            # Consider navigating back to a previous menu if refresh isn't possible
            await cq_show_manage_muted_menu(callback_query, language, user_specific_settings, NotificationActionCallback(action="manage_muted"))

    elif list_type in ["muted", "allowed"]:
        await _display_paginated_user_list(callback_query, language, user_specific_settings, list_type, current_page)
    else:
        # This case should have been caught earlier, but as a fallback:
        logger.error(f"Unknown list_type '{list_type}' for refresh in cq_toggle_specific_user_mute_action")
        await callback_query.answer("Error: Could not refresh list due to unknown list type.", show_alert=True)


# The SEARCH block for _create_manage_muted_users_keyboard needs to be provided to make this change.
# For now, this diff only reflects changes within the "Mute/Unmute from Server User List Callbacks" section
# and the cq_toggle_specific_user_mute_action handler.
# The calling UserListCallback instantiation in _create_manage_muted_users_keyboard is outside this direct diff's scope.
# This will be handled by a separate replace for _create_manage_muted_users_keyboard if the tool allows another call,
# or manually noted if this is the last modification to the file.

# Assuming the UserListCallback change in _create_manage_muted_users_keyboard is done separately or was part of an earlier step's context for that function.
# The current diff focuses on renaming and adapting the server list functions and their direct callers for pagination and toggling.
