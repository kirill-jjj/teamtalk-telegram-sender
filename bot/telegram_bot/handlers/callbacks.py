import logging
import math # For pagination
from typing import Callable
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.exceptions import PermissionError as PytalkPermissionError # Alias to avoid potential name clashes

from bot.localization import get_text
from bot.core.user_settings import UserSpecificSettings, update_user_settings_in_db
from bot.telegram_bot.filters import IsAdminFilter
from bot.telegram_bot.keyboards import (
    create_main_settings_keyboard,
    create_language_selection_keyboard,
    create_subscription_settings_keyboard,
    create_notification_settings_keyboard,
    create_manage_muted_users_keyboard,
    create_paginated_user_list_keyboard,
    create_account_list_keyboard
)
from bot.constants import (
    CALLBACK_ACTION_KICK, CALLBACK_ACTION_BAN,
    USERS_PER_PAGE
)

from bot.state import USER_ACCOUNTS_CACHE

logger = logging.getLogger(__name__)
callback_router = Router(name="callback_router")
ttstr = pytalk.instance.sdk.ttstr


async def _process_setting_update(
    callback_query: CallbackQuery,
    session: AsyncSession,
    user_settings: UserSpecificSettings,
    language: str, # For error messages
    update_action: Callable[[], None],
    revert_action: Callable[[], None],
    success_toast_text: str,
    ui_refresh_callable: Callable[[], tuple[str, InlineKeyboardMarkup]]
) -> None:
    if not callback_query.message or not callback_query.from_user:
        # This check might be redundant if callers ensure message/from_user exist,
        # but good for a generic helper.
        logger.warning("_process_setting_update called with no message or from_user in callback_query.")
        await callback_query.answer("Error: Callback query is missing essential data.", show_alert=True)
        return

    update_action() # Apply change in memory

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_settings)
        # Send success toast only after successful DB update
        await callback_query.answer(success_toast_text, show_alert=False)
    except Exception as e:
        logger.error(
            f"Failed to update settings in DB for user {callback_query.from_user.id}. Error: {e}",
            exc_info=True
        )
        revert_action() # Revert change in memory
        try:
            # Try to inform user of failure
            await callback_query.answer(get_text("error_occurred", language), show_alert=True)
        except TelegramAPIError as ans_err:
            logger.warning(f"Could not send error alert for DB update failure: {ans_err}")
        return # Stop further processing like UI refresh if DB save failed

    # If DB update was successful, proceed to refresh UI
    try:
        new_text, new_markup = ui_refresh_callable()
        await callback_query.message.edit_text(text=new_text, reply_markup=new_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message after setting update for user {callback_query.from_user.id}: {e}")
        # If message is not modified, it's not a critical error, toast was already sent.
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message after setting update for user {callback_query.from_user.id}: {e}")
    except Exception as e_refresh: # Catch any other errors during UI refresh
        logger.error(f"Unexpected error during UI refresh for user {callback_query.from_user.id}: {e_refresh}", exc_info=True)
        # UI refresh failed, but setting was saved. Maybe send a simple text message if edit failed?
        # For now, just log, as the primary action (setting update) was successful.


async def _execute_tt_user_action(
    action_val: str,
    user_id_val: int,
    user_nickname_val: str, # This is the potentially truncated nickname from callback data
    language: str,
    tt_instance: TeamTalkInstance,
    admin_tg_id: int
) -> str:
    try:
        user_to_act_on = tt_instance.server.get_user(user_id_val) # Fetches the TeamTalkUser object

        if user_to_act_on:
            # It's good to use the full nickname from the user object for messages if available,
            # but user_nickname_val (from callback) is what we have confirmed.
            # For logging and messages, let's try to get the most current display name.
            # This requires access to ttstr or a similar utility. Assuming ttstr is module level.
            # If user_to_act_on.nickname is empty, ttstr(user_to_act_on.username) would be used.
            # We'll use html.quote on the display name for safety in messages.

            # For consistency with previous logs and messages, we'll use the user_nickname_val
            # passed from the callback for user-facing messages, as that's what they saw on the button.
            # For logging, we can use more detailed info from user_to_act_on if needed.

            quoted_nickname = html.quote(user_nickname_val) # Use the nickname from callback for messages

            if action_val == "kick":
                user_to_act_on.kick(from_server=True)
                logger.info(f"Admin {admin_tg_id} kicked TT user '{user_nickname_val}' (ID: {user_id_val}, Full Nick: {ttstr(user_to_act_on.nickname)}, User: {ttstr(user_to_act_on.username)})")
                return get_text("CALLBACK_USER_KICKED", language, user_nickname=quoted_nickname)

            elif action_val == "ban":
                user_to_act_on.ban(from_server=True)
                user_to_act_on.kick(from_server=True) # Ensure kick after ban
                logger.info(f"Admin {admin_tg_id} banned and kicked TT user '{user_nickname_val}' (ID: {user_id_val}, Full Nick: {ttstr(user_to_act_on.nickname)}, User: {ttstr(user_to_act_on.username)})")
                return get_text("CALLBACK_USER_BANNED_KICKED", language, user_nickname=quoted_nickname)

            # Should not happen if action_val is validated by the caller, but as a fallback:
            else:
                logger.warning(f"Unknown action '{action_val}' attempted in _execute_tt_user_action for user ID {user_id_val}")
                return get_text("CALLBACK_UNKNOWN_ACTION", language) # Or a more specific error

        else: # user_to_act_on is None
            logger.warning(f"Admin {admin_tg_id} tried to {action_val} TT user ID {user_id_val} (Nickname on button: '{user_nickname_val}'), but user was not found.")
            # Pass user_nickname_val to the message as it's the context the admin had
            return get_text("CALLBACK_USER_NOT_FOUND_ANYMORE", language, user_nickname=html.quote(user_nickname_val))

    except PytalkPermissionError as e:
        quoted_nickname_for_error = html.quote(user_nickname_val)
        logger.error(
            f"PermissionError during '{action_val}' on TT user '{user_nickname_val}' (ID: {user_id_val}) by admin {admin_tg_id}: {e}",
            exc_info=True
        )
        # Assuming CALLBACK_ERROR_PERMISSION is a key like:
        # "You do not have permission to {action} user {user_nickname}. Error: {error}"
        # or more simply: "Insufficient permissions to perform {action} on {user_nickname}."
        # For now, let's make it simpler and not pass the raw error 'e' to the user message for permission errors.
        return get_text("CALLBACK_ERROR_PERMISSION", language,
                        action=action_val,
                        user_nickname=quoted_nickname_for_error)

    except ValueError as e:
        # This can occur if user_id_val is somehow not a valid format for get_user,
        # or other ValueErrors within the try block.
        quoted_nickname_for_error = html.quote(user_nickname_val)
        logger.warning(
            f"ValueError during '{action_val}' on TT user '{user_nickname_val}' (ID: {user_id_val}) by admin {admin_tg_id}: {e}. This might indicate user not found or invalid ID.",
            exc_info=True # Log with traceback for diagnosis
        )
        # Reusing the existing text for "user not found" seems appropriate here.
        return get_text("CALLBACK_USER_NOT_FOUND_ANYMORE", language, user_nickname=quoted_nickname_for_error)

    except Exception as e:
        # Ensure user_nickname_val is quoted for the error message too.
        quoted_nickname_for_error = html.quote(user_nickname_val)
        # Construct the key for the gerund text dynamically (specific to Russian for CALLBACK_ERROR_ACTION_USER)
        gerund_key = f"CALLBACK_ACTION_{action_val.upper()}_GERUND_RU"
        action_ru = get_text(gerund_key, "ru") # This is for a specific language, check if CALLBACK_ERROR_ACTION_USER needs it

        logger.error( # Use logger.error for unexpected exceptions
            f"Unexpected error during '{action_val}' action on TT user '{user_nickname_val}' (ID: {user_id_val}) by admin {admin_tg_id}: {e}",
            exc_info=True # Crucial for debugging unexpected errors
        )
        return get_text("CALLBACK_ERROR_ACTION_USER", language,
                        action=action_val,
                        action_ru=action_ru, # Kept for compatibility with existing localization
                        user_nickname=quoted_nickname_for_error,
                        error=str(e))

@callback_router.callback_query(F.data.startswith(f"{CALLBACK_ACTION_KICK}:") | F.data.startswith(f"{CALLBACK_ACTION_BAN}:"))
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

    # The USER_ACTION_CALLBACK_HANDLERS dictionary and individual handlers were removed.
    # Direct call to _execute_tt_user_action after admin check.

    reply_text_val: str # Declare type for clarity, will be assigned below.

    # Admin check for kick/ban actions
    # The callback_router filter F.data.startswith(f"{CALLBACK_ACTION_KICK}:") | F.data.startswith(f"{CALLBACK_ACTION_BAN}:")
    # ensures action_val will be one of these.
    if action_val in [CALLBACK_ACTION_KICK, CALLBACK_ACTION_BAN]:
        is_admin_caller = await IsAdminFilter()(callback_query, session)
        if not is_admin_caller:
            await callback_query.answer(get_text("CALLBACK_NO_PERMISSION", language), show_alert=True)
            return

        # If admin check passes, call the unified handler
        # tt_instance is confirmed not None from the check above.
        reply_text_val = await _execute_tt_user_action(
            action_val=action_val,
            user_id_val=user_id_val,
            user_nickname_val=user_nickname_val, # This is the (potentially truncated) nickname from callback
            language=language,
            tt_instance=tt_instance,
            admin_tg_id=callback_query.from_user.id
        )
    else:
        # This case should ideally not be reached due to the F.data.startswith filter on the handler.
        # However, as a defensive measure:
        logger.warning(f"Unexpected action '{action_val}' reached main logic in process_user_action_selection despite filters.")
        reply_text_val = get_text("CALLBACK_UNKNOWN_ACTION", language)

    try:
        await callback_query.message.edit_text(reply_text_val, reply_markup=None) # Clear buttons after action
    except TelegramAPIError as e:
        logger.error(f"Error editing message after user action callback: {e}")




# --- Settings Callbacks ---

from bot.telegram_bot.callback_data import (
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
async def cq_show_language_menu(
    callback_query: CallbackQuery,
    language: str, # Current language from UserSettingsMiddleware
    callback_data: SettingsCallback # Consumes the SettingsCallback
):
    if not callback_query.message: # Should not happen
        await callback_query.answer("Error: No message associated with callback.")
        return
    await callback_query.answer() # Acknowledge

    # Create language selection buttons using factory
    language_menu_builder = create_language_selection_keyboard(language)

    try:
        await callback_query.message.edit_text(
            text=get_text("CHOOSE_LANGUAGE_PROMPT", language),
            reply_markup=language_menu_builder.as_markup()
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
        # This initial check can remain, or be moved into the helper if preferred,
        # but for now, keeping it here is fine as it's a precondition.
        await callback_query.answer("Error: Missing data for language update.", show_alert=True)
        return

    new_lang_code = callback_data.lang_code
    original_lang_code = user_specific_settings.language

    # Ensure this check is done before update_action
    if new_lang_code == original_lang_code:
        await callback_query.answer() # Answer to remove loading state from button
        return


    def update_logic():
        user_specific_settings.language = new_lang_code

    def revert_logic():
        user_specific_settings.language = original_lang_code

    lang_name_display = get_text(f"LANGUAGE_BTN_{new_lang_code.upper()}", new_lang_code)
    toast_text = get_text("LANGUAGE_UPDATED_TO", new_lang_code, lang_name=lang_name_display)

    def refresh_ui() -> tuple[str, InlineKeyboardMarkup]:
        # After setting language, go back to the main settings menu, now in the new language
        main_settings_builder = create_main_settings_keyboard(new_lang_code)
        main_settings_text = get_text("SETTINGS_MENU_HEADER", new_lang_code)
        return main_settings_text, main_settings_builder.as_markup()

    await _process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        language=new_lang_code, # Pass the new language for potential error messages in that lang
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=toast_text,
        ui_refresh_callable=refresh_ui
    )


# --- Subscription Settings Callbacks ---

from bot.database.models import NotificationSetting

@callback_router.callback_query(SettingsCallback.filter(F.action == "subscriptions"))
async def cq_show_subscriptions_menu(
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
    # Use factory from keyboards.py
    subscription_settings_builder = create_subscription_settings_keyboard(language, current_notification_setting)

    try:
        await callback_query.message.edit_text(
            text=get_text("SUBS_SETTINGS_MENU_HEADER", language),
            reply_markup=subscription_settings_builder.as_markup()
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
    language: str, # Current language from UserSettingsMiddleware
    user_specific_settings: UserSpecificSettings,
    callback_data: SubscriptionCallback
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer("Error: Missing data.", show_alert=True)
        return

    value_to_enum_map = {
        "all": NotificationSetting.ALL,
        "leave_off": NotificationSetting.LEAVE_OFF,
        "join_off": NotificationSetting.JOIN_OFF,
        "none": NotificationSetting.NONE,
    }
    new_setting_enum = value_to_enum_map.get(callback_data.setting_value)

    if new_setting_enum is None:
        logger.error(f"Invalid subscription setting value: {callback_data.setting_value} for user {callback_query.from_user.id}")
        await callback_query.answer("Error: Invalid setting value.", show_alert=True)
        return

    original_setting = user_specific_settings.notification_settings

    if new_setting_enum == original_setting:
        await callback_query.answer() # Answer to remove loading state
        return

    def update_logic():
        user_specific_settings.notification_settings = new_setting_enum

    def revert_logic():
        user_specific_settings.notification_settings = original_setting

    setting_to_text_key = {
        NotificationSetting.ALL: "SUBS_SETTING_ALL_BTN",
        NotificationSetting.LEAVE_OFF: "SUBS_SETTING_JOIN_ONLY_BTN",
        NotificationSetting.JOIN_OFF: "SUBS_SETTING_LEAVE_ONLY_BTN",
        NotificationSetting.NONE: "SUBS_SETTING_NONE_BTN",
    }
    setting_text_key = setting_to_text_key.get(new_setting_enum, "unknown_setting")
    setting_display_name = get_text(setting_text_key, language)
    toast_text = get_text("SUBS_SETTING_UPDATED_TO", language, setting_name=setting_display_name)

    def refresh_ui() -> tuple[str, InlineKeyboardMarkup]:
        updated_builder = create_subscription_settings_keyboard(language, new_setting_enum) # Pass new_setting_enum
        menu_text = get_text("SUBS_SETTINGS_MENU_HEADER", language)
        return menu_text, updated_builder.as_markup()

    await _process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        language=language, # Current language is fine for error messages here
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=toast_text,
        ui_refresh_callable=refresh_ui
    )

# This handler now manages returns to the main settings menu
@callback_router.callback_query(SettingsCallback.filter(F.action == "back_to_main"))
async def cq_back_to_main_settings_menu(
    callback_query: CallbackQuery,
    language: str, # From UserSettingsMiddleware
    callback_data: SettingsCallback # Consumes the callback
):
    if not callback_query.message:
        await callback_query.answer("Error: No message.")
        return
    await callback_query.answer() # Acknowledge

    # Re-create main settings menu using factory
    main_settings_builder = create_main_settings_keyboard(language)

    try:
        await callback_query.message.edit_text(
            text=get_text("SETTINGS_MENU_HEADER", language),
            reply_markup=main_settings_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for back_to_main_settings_menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for back_to_main_settings_menu: {e}")


# --- Notification Settings Callbacks ---

@callback_router.callback_query(SettingsCallback.filter(F.action == "notifications"))
async def cq_show_notifications_menu(
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: SettingsCallback # Consumes SettingsCallback
):
    if not callback_query.message:
        await callback_query.answer("Error: No message.")
        return
    await callback_query.answer()
    # Use factory from keyboards.py
    notification_settings_builder = create_notification_settings_keyboard(language, user_specific_settings)
    try:
        await callback_query.message.edit_text(
            text=get_text("NOTIF_SETTINGS_MENU_HEADER", language),
            reply_markup=notification_settings_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for notification settings menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for notification settings menu: {e}")

# Refactored cq_toggle_noon_setting
@callback_router.callback_query(NotificationActionCallback.filter(F.action == "toggle_noon"))
async def cq_toggle_noon_setting_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str, # Current language from UserSettingsMiddleware
    user_specific_settings: UserSpecificSettings,
    callback_data: NotificationActionCallback # Consumes NotificationActionCallback
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer("Error: Missing data.", show_alert=True)
        return

    # The user_specific_settings.not_on_online_enabled is toggled directly in update_logic.
    # We need its original state for revert_logic and to determine the new status for the toast.
    original_noon_status = user_specific_settings.not_on_online_enabled

    def update_logic():
        user_specific_settings.not_on_online_enabled = not original_noon_status

    def revert_logic():
        user_specific_settings.not_on_online_enabled = original_noon_status

    # Determine the status text based on the state *after* the toggle
    new_status_text_key = "ENABLED_STATUS" if not original_noon_status else "DISABLED_STATUS"
    new_status_display_text = get_text(new_status_text_key, language)
    toast_text = get_text("NOTIF_SETTING_NOON_UPDATED_TO", language, status=new_status_display_text)

    def refresh_ui() -> tuple[str, InlineKeyboardMarkup]:
        # user_specific_settings will have the updated not_on_online_enabled value here
        updated_builder = create_notification_settings_keyboard(language, user_specific_settings)
        menu_text = get_text("NOTIF_SETTINGS_MENU_HEADER", language)
        return menu_text, updated_builder.as_markup()

    # The initial callback_query.answer() acknowledging the action is removed
    # as _process_setting_update handles answers (toast or error alert).

    await _process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        language=language, # User's current language
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=toast_text,
        ui_refresh_callable=refresh_ui
    )


# --- Manage Muted Users Callbacks ---

@callback_router.callback_query(NotificationActionCallback.filter(F.action == "manage_muted"))
async def cq_show_manage_muted_menu(
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: NotificationActionCallback # Consumes
):
    if not callback_query.message:
        await callback_query.answer("Error: No message.")
        return
    await callback_query.answer()
    # Use factory from keyboards.py
    manage_muted_builder = create_manage_muted_users_keyboard(language, user_specific_settings)
    try:
        await callback_query.message.edit_text(
            text=get_text("MANAGE_MUTED_MENU_HEADER", language),
            reply_markup=manage_muted_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for manage_muted_users menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for manage_muted_users menu: {e}")

# Refactored cq_toggle_mute_all_setting
@callback_router.callback_query(MuteAllCallback.filter(F.action == "toggle_mute_all"))
async def cq_toggle_mute_all_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    language: str, # Current language from UserSettingsMiddleware
    user_specific_settings: UserSpecificSettings,
    callback_data: MuteAllCallback # Consumes
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer("Error: Missing data.", show_alert=True)
        return

    original_flag = user_specific_settings.mute_all_flag

    def update_logic():
        user_specific_settings.mute_all_flag = not original_flag

    def revert_logic():
        user_specific_settings.mute_all_flag = original_flag

    # Determine the status text based on the state *after* the toggle
    new_status_text_key = "ENABLED_STATUS" if not original_flag else "DISABLED_STATUS"
    new_status_display_text = get_text(new_status_text_key, language)
    toast_text = get_text("MUTE_ALL_UPDATED_TO", language, status=new_status_display_text)

    def refresh_ui() -> tuple[str, InlineKeyboardMarkup]:
        # user_specific_settings will have the updated mute_all_flag value here
        updated_builder = create_manage_muted_users_keyboard(language, user_specific_settings)
        menu_text = get_text("MANAGE_MUTED_MENU_HEADER", language)
        return menu_text, updated_builder.as_markup()

    # The initial callback_query.answer() is removed as _process_setting_update handles it.
    await _process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        language=language, # User's current language
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=toast_text,
        ui_refresh_callable=refresh_ui
    )

# --- Paginated User List for Muted/Allowed Users (Refactored) ---

async def _display_paginated_list(
    callback_query: CallbackQuery,
    language: str,
    items: list, # This is the full list of items to paginate
    page: int, # The requested page number
    header_text_key: str,
    empty_list_text_key: str,
    keyboard_factory: Callable[..., InlineKeyboardMarkup],
    keyboard_factory_kwargs: dict
) -> None:
    """
    Generic helper to display a paginated list in a Telegram message.
    """
    if not callback_query.message:
        return

    page_slice, total_pages, current_page = _paginate_list(items, page, USERS_PER_PAGE)

    message_parts = [get_text(header_text_key, language)]

    if not items: # Check if the original full list is empty
        message_parts.append(get_text(empty_list_text_key, language))

    # Page indicator should always be present if there's a message to display
    # It's added after the potential empty list message.
    page_indicator_text = get_text("PAGE_INDICATOR", language, current_page=current_page + 1, total_pages=total_pages)
    message_parts.append(f"\n{page_indicator_text}") # Add a newline before page indicator for better separation

    final_message_text = "\n".join(message_parts)

    # Prepare keyboard
    # Common arguments for keyboard factories are language, page_slice (as page_items), current_page, total_pages.
    # Specific keyboard factories might need other arguments, passed via keyboard_factory_kwargs.
    keyboard_markup = keyboard_factory(
        language=language,
        page_items=page_slice, # Pass the slice of items for the current page
        current_page=current_page,
        total_pages=total_pages,
        **keyboard_factory_kwargs
    )

    try:
        await callback_query.message.edit_text(
            text=final_message_text,
            reply_markup=keyboard_markup,
            parse_mode="HTML" # Assuming HTML parse mode as it's common in the project
        )
    except TelegramBadRequest as e:
        # Avoid logging if the message content is identical, as this is a common scenario
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest in _display_paginated_list for {header_text_key}: {e}", exc_info=True)
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError in _display_paginated_list for {header_text_key}: {e}", exc_info=True)
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"Unexpected error in _display_paginated_list for {header_text_key}: {e}", exc_info=True)


def _paginate_list(full_list: list, page: int, page_size: int) -> tuple[list, int, int]:
    total_items = len(full_list)

    # Calculate total_pages, ensuring it's at least 1, and an integer.
    # This handles the case where full_list is empty (total_items = 0), resulting in total_pages = 1.
    total_pages = int(math.ceil(total_items / page_size)) if total_items > 0 else 1

    # Correct page to be 0-indexed and within bounds [0, total_pages - 1].
    # If total_pages is 1 (e.g., list is empty or fits one page), max valid page index is 0.
    # max(0, min(page, 0)) correctly yields 0 if page was <0 or >0.
    page = max(0, min(page, total_pages - 1))

    start_index = page * page_size
    end_index = start_index + page_size # Slicing handles end_index > total_items gracefully.

    page_slice = full_list[start_index:end_index]

    return page_slice, total_pages, page


async def _display_paginated_user_list(
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    list_type: str,
    page: int = 0
):
    if not callback_query.message: return # Keep this initial check

    # Determine the source of items based on list_type and user_specific_settings.
    # The set user_specific_settings.muted_users_set contains users that are muted (when mute_all_flag is False)
    # or users that are allowed (when mute_all_flag is True, these are exceptions to mute all).
    # The keyboard factory create_paginated_user_list_keyboard handles the display logic based on list_type and the actual mute state.
    users_to_process = user_specific_settings.muted_users_set
    sorted_items = sorted(list(users_to_process))

    header_key = "MUTED_USERS_LIST_HEADER" if list_type == "muted" else "ALLOWED_USERS_LIST_HEADER"
    empty_key = "NO_MUTED_USERS_FOUND" if list_type == "muted" else "NO_ALLOWED_USERS_FOUND"

    # The `create_paginated_user_list_keyboard` factory will require:
    # language (from _display_paginated_list's standard arguments)
    # page_items (this will be page_slice from _display_paginated_list's standard arguments)
    # current_page (from _display_paginated_list's standard arguments)
    # total_pages (from _display_paginated_list's standard arguments)
    # list_type (specific to this keyboard, passed via keyboard_factory_kwargs)
    # user_specific_settings (specific to this keyboard, passed via keyboard_factory_kwargs)

    await _display_paginated_list(
        callback_query=callback_query,
        language=language,
        items=sorted_items, # Pass the full sorted list of relevant usernames/items
        page=page,
        header_text_key=header_key,
        empty_list_text_key=empty_key,
        keyboard_factory=create_paginated_user_list_keyboard, # Function reference
        keyboard_factory_kwargs={ # Arguments specific to create_paginated_user_list_keyboard
            "list_type": list_type,
            "user_specific_settings": user_specific_settings
        }
    )

# Consolidated handler for listing muted/allowed users
@callback_router.callback_query(UserListCallback.filter(F.action.in_(["list_muted", "list_allowed"])))
async def cq_list_internal_users(
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
async def cq_paginate_internal_user_list(
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings,
    callback_data: PaginateUsersCallback
):
    # _display_paginated_user_list will .answer()
    await _display_paginated_user_list(
        callback_query, language, user_specific_settings, callback_data.list_type, callback_data.page
    )


# --- Mute/Unmute from Server Account List Callbacks ---

async def _display_account_list(
    callback_query: CallbackQuery,
    language: str,
    user_specific_settings: UserSpecificSettings, # Needed for keyboard factory
    tt_instance: TeamTalkInstance, # Keep for USER_ACCOUNTS_CACHE check (though not directly used if cache populated)
    page: int = 0
):
    if not callback_query.message: return # Keep this initial check

    if not USER_ACCOUNTS_CACHE: # Check if cache is empty
        # Attempt to edit the message, or answer callback if message is not available/editable
        try:
            if callback_query.message:
                await callback_query.message.edit_text(get_text("NO_SERVER_ACCOUNTS_FOUND", language))
            else: # Fallback if message is somehow gone
                await callback_query.answer(get_text("NO_SERVER_ACCOUNTS_FOUND", language), show_alert=True)
        except TelegramAPIError as e: # Catch potential errors during edit_text or answer
            logger.error(f"Error informing user about empty USER_ACCOUNTS_CACHE: {e}")
        return

    all_accounts_tt = list(USER_ACCOUNTS_CACHE.values())
    # Assuming acc.username is how pytalk.UserAccount stores username.
    # ttstr should be available in the module scope.
    sorted_items = sorted(
        all_accounts_tt,
        key=lambda acc: ttstr(acc.username).lower()
    )

    # The `create_account_list_keyboard` factory will require:
    # language (from _display_paginated_list)
    # page_items (this will be page_slice from _display_paginated_list)
    # current_page (from _display_paginated_list)
    # total_pages (from _display_paginated_list)
    # user_specific_settings (specific to this keyboard, passed via keyboard_factory_kwargs)

    await _display_paginated_list(
        callback_query=callback_query,
        language=language,
        items=sorted_items, # Pass the full sorted list of account objects
        page=page,
        header_text_key="ALL_ACCOUNTS_LIST_HEADER",
        empty_list_text_key="NO_SERVER_ACCOUNTS_FOUND", # Shown if sorted_items is empty
        keyboard_factory=create_account_list_keyboard, # Function reference
        keyboard_factory_kwargs={ # Arguments specific to create_account_list_keyboard
            "user_specific_settings": user_specific_settings
        }
    )

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
async def cq_paginate_all_accounts_list_action(
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
async def cq_toggle_specific_user_mute_action(
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
            all_accounts_tt = list(USER_ACCOUNTS_CACHE.values())
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
