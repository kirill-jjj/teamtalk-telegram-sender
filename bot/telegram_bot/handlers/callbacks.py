import logging
import math # For pagination
from typing import Callable, Any
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.exceptions import PermissionError as PytalkPermissionError # Alias to avoid potential name clashes

# from bot.localization import get_text # Removed
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
    _: callable, # Changed from language: str
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
            await callback_query.answer(_("An error occurred."), show_alert=True) # error_occurred
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
    _: callable, # Changed from language: str
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
                return _("User {user_nickname} kicked from server.").format(user_nickname=quoted_nickname) # CALLBACK_USER_KICKED (Adjusted to example)

            elif action_val == "ban":
                user_to_act_on.ban(from_server=True)
                user_to_act_on.kick(from_server=True) # Ensure kick after ban
                logger.info(f"Admin {admin_tg_id} banned and kicked TT user '{user_nickname_val}' (ID: {user_id_val}, Full Nick: {ttstr(user_to_act_on.nickname)}, User: {ttstr(user_to_act_on.username)})")
                return _("User {user_nickname} banned and kicked from server.").format(user_nickname=quoted_nickname) # CALLBACK_USER_BANNED_KICKED (Adjusted to example)

            else:
                logger.warning(f"Unknown action '{action_val}' attempted in _execute_tt_user_action for user ID {user_id_val}")
                return _("Unknown action.") # CALLBACK_UNKNOWN_ACTION

        else: # user_to_act_on is None
            logger.warning(f"Admin {admin_tg_id} tried to {action_val} TT user ID {user_id_val} (Nickname on button: '{user_nickname_val}'), but user was not found.")
            return _("User not found on server anymore.").format(user_nickname=html.quote(user_nickname_val)) # CALLBACK_USER_NOT_FOUND_ANYMORE (Adjusted)

    except PytalkPermissionError as e:
        quoted_nickname_for_error = html.quote(user_nickname_val)
        logger.error(
            f"PermissionError during '{action_val}' on TT user '{user_nickname_val}' (ID: {user_id_val}) by admin {admin_tg_id}: {e}",
            exc_info=True
        )
        # Using a simpler permission error string
        return _("You do not have permission to {action} user {user_nickname}.").format(action=action_val, user_nickname=quoted_nickname_for_error) # CALLBACK_ERROR_PERMISSION

    except ValueError as e:
        quoted_nickname_for_error = html.quote(user_nickname_val)
        logger.warning(
            f"ValueError during '{action_val}' on TT user '{user_nickname_val}' (ID: {user_id_val}) by admin {admin_tg_id}: {e}. This might indicate user not found or invalid ID.",
            exc_info=True
        )
        return _("User not found on server anymore.").format(user_nickname=quoted_nickname_for_error) # CALLBACK_USER_NOT_FOUND_ANYMORE (Adjusted)

    except Exception as e:
        quoted_nickname_for_error = html.quote(user_nickname_val)
        logger.error(
            f"Unexpected error during '{action_val}' action on TT user '{user_nickname_val}' (ID: {user_id_val}) by admin {admin_tg_id}: {e}",
            exc_info=True
        )
        # Generic error message for user, specific error logged
        return _("Error {action}ing user {user_nickname}: {error_message}").format(action=action_val, user_nickname=quoted_nickname_for_error, error_message=str(e)) # CALLBACK_ERROR_ACTION_USER (Simplified error_message)

@callback_router.callback_query(F.data.startswith(f"{CALLBACK_ACTION_KICK}:") | F.data.startswith(f"{CALLBACK_ACTION_BAN}:"))
async def process_user_action_selection(
    callback_query: CallbackQuery,
    session: AsyncSession, # From DbSessionMiddleware
    # language: str, # From UserSettingsMiddleware - REMOVED
    tt_instance: TeamTalkInstance | None, # From TeamTalkInstanceMiddleware
    data: dict[str, Any] # To get `_`
):
    _ = data["_"] # Translator function
    await callback_query.answer() # Acknowledge the callback quickly
    if not callback_query.message or not callback_query.from_user: return

    try:
        action_val, user_id_str_val, user_nickname_val = callback_query.data.split(":", 2)
        user_id_val = int(user_id_str_val)
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data format for user action: {callback_query.data}")
        await callback_query.message.edit_text(_("Invalid data received.")) # CALLBACK_INVALID_DATA
        return

    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
         await callback_query.message.edit_text(_("TeamTalk bot is not connected.")) # TT_BOT_NOT_CONNECTED
         return

    reply_text_val: str

    if action_val in [CALLBACK_ACTION_KICK, CALLBACK_ACTION_BAN]:
        is_admin_caller = await IsAdminFilter()(callback_query, session)
        if not is_admin_caller:
            await callback_query.answer(_("You do not have permission to execute this action."), show_alert=True) # CALLBACK_NO_PERMISSION
            return

        reply_text_val = await _execute_tt_user_action(
            action_val=action_val,
            user_id_val=user_id_val,
            user_nickname_val=user_nickname_val,
            _=_, # Pass the translator
            tt_instance=tt_instance,
            admin_tg_id=callback_query.from_user.id
        )
    else:
        logger.warning(f"Unexpected action '{action_val}' reached main logic in process_user_action_selection despite filters.")
        reply_text_val = _("Unknown action.") # CALLBACK_UNKNOWN_ACTION

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

from bot.language import get_translator # Added import

@callback_router.callback_query(SettingsCallback.filter(F.action == "language"))
async def cq_show_language_menu(
    callback_query: CallbackQuery,
    callback_data: SettingsCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with callback."))
        return
    await callback_query.answer()

    language_menu_builder = create_language_selection_keyboard(_)

    try:
        await callback_query.message.edit_text(
            text=_("Please choose your language:"),
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
    callback_data: LanguageCallback, # Consumes LanguageCallback
    data: dict[str, Any]
):
    # _ for current language errors, _new for new language UI
    _current = data["_"]
    if not callback_query.message or not callback_query.from_user or not callback_data.lang_code:
        await callback_query.answer(_current("Error: Missing data for language update."), show_alert=True)
        return

    new_lang_code = callback_data.lang_code
    original_lang_code = user_specific_settings.language

    if new_lang_code == original_lang_code:
        await callback_query.answer()
        return

    # For messages in the new language, we need a new translator
    # This is tricky because `_process_setting_update` expects a single `_` for its error messages.
    # For this specific handler, messages (toast, new menu) should be in the *new* language.
    # The success_toast_text and ui_refresh_callable will use a translator for the new_lang_code.

    # Get translator for the new language for UI and toast
    new_lang_translator_obj = get_translator(new_lang_code)
    _new = new_lang_translator_obj.gettext

    def update_logic():
        user_specific_settings.language = new_lang_code

    def revert_logic():
        user_specific_settings.language = original_lang_code

    # The key for language button (e.g., "LANGUAGE_BTN_EN") should give the language name in that language itself.
    # So, "English" for "en", "Русский" for "ru".
    # We use _new to get this display name in the target language.
    lang_name_display = _new(f"LANGUAGE_BTN_{new_lang_code.upper()}") # This assumes keys like LANGUAGE_BTN_EN exist
    toast_text = _new("Language updated to {lang_name}.").format(lang_name=lang_name_display) # LANGUAGE_UPDATED_TO

    def refresh_ui() -> tuple[str, InlineKeyboardMarkup]:
        main_settings_builder = create_main_settings_keyboard(_new) # create_main_settings_keyboard expects `_`
        main_settings_text = _new("⚙️ Settings") # SETTINGS_MENU_HEADER
        return main_settings_text, main_settings_builder.as_markup()

    # _process_setting_update needs a single `_` for its internal error messages.
    # We'll pass the one for the new language, as that's the most sensible for this context.
    await _process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        _= _new, # Pass translator for the new language
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
    # language: str, # REMOVED
    user_specific_settings: UserSpecificSettings,
    callback_data: SettingsCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with callback."))
        return
    await callback_query.answer()

    current_notification_setting = user_specific_settings.notification_settings
    subscription_settings_builder = create_subscription_settings_keyboard(_, current_notification_setting)

    try:
        await callback_query.message.edit_text(
            text=_("Subscription Settings"),
            reply_markup=subscription_settings_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for subscription settings menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for subscription settings menu: {e}")

@callback_router.callback_query(SubscriptionCallback.filter(F.action == "set_sub"))
async def cq_set_subscription_setting(
    callback_query: CallbackQuery,
    session: AsyncSession,
    # language: str, # REMOVED
    user_specific_settings: UserSpecificSettings,
    callback_data: SubscriptionCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer(_("Error: Missing data for subscription update."), show_alert=True)
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
        await callback_query.answer(_("Error: Invalid setting value received."), show_alert=True)
        return

    original_setting = user_specific_settings.notification_settings

    if new_setting_enum == original_setting:
        await callback_query.answer()
        return

    def update_logic():
        user_specific_settings.notification_settings = new_setting_enum

    def revert_logic():
        user_specific_settings.notification_settings = original_setting

    setting_to_text_map = {
        NotificationSetting.ALL: _("All (Join & Leave)"), # SUBS_SETTING_ALL_BTN
        NotificationSetting.LEAVE_OFF: _("Join Only"),  # SUBS_SETTING_JOIN_ONLY_BTN (text is for what's enabled)
        NotificationSetting.JOIN_OFF: _("Leave Only"), # SUBS_SETTING_LEAVE_ONLY_BTN (text is for what's enabled)
        NotificationSetting.NONE: _("None"),          # SUBS_SETTING_NONE_BTN
    }
    setting_display_name = setting_to_text_map.get(new_setting_enum, _("unknown setting"))
    toast_text = _("Subscription setting updated to: {setting_name}").format(setting_name=setting_display_name) # SUBS_SETTING_UPDATED_TO

    def refresh_ui() -> tuple[str, InlineKeyboardMarkup]:
        updated_builder = create_subscription_settings_keyboard(_, new_setting_enum)
        menu_text = _("Subscription Settings") # SUBS_SETTINGS_MENU_HEADER
        return menu_text, updated_builder.as_markup()

    await _process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=toast_text,
        ui_refresh_callable=refresh_ui
    )

@callback_router.callback_query(SettingsCallback.filter(F.action == "back_to_main"))
async def cq_back_to_main_settings_menu(
    callback_query: CallbackQuery,
    # language: str, # REMOVED
    callback_data: SettingsCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with callback."))
        return
    await callback_query.answer()

    main_settings_builder = create_main_settings_keyboard(_)

    try:
        await callback_query.message.edit_text(
            text=_("⚙️ Settings"),
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
    # language: str, # REMOVED
    user_specific_settings: UserSpecificSettings,
    callback_data: SettingsCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with callback."))
        return
    await callback_query.answer()
    notification_settings_builder = create_notification_settings_keyboard(_, user_specific_settings)
    try:
        await callback_query.message.edit_text(
            text=_("Notification Settings"),
            reply_markup=notification_settings_builder.as_markup()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for notification settings menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for notification settings menu: {e}")

@callback_router.callback_query(NotificationActionCallback.filter(F.action == "toggle_noon"))
async def cq_toggle_noon_setting_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    # language: str, # REMOVED
    user_specific_settings: UserSpecificSettings,
    callback_data: NotificationActionCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer(_("Error: Missing data for NOON toggle."), show_alert=True)
        return

    original_noon_status = user_specific_settings.not_on_online_enabled

    def update_logic():
        user_specific_settings.not_on_online_enabled = not original_noon_status

    def revert_logic():
        user_specific_settings.not_on_online_enabled = original_noon_status

    new_status_display_text = _("Enabled") if not original_noon_status else _("Disabled") # ENABLED_STATUS, DISABLED_STATUS
    toast_text = _("NOON (Not on Online) is now {status}.").format(status=new_status_display_text) # NOTIF_SETTING_NOON_UPDATED_TO

    def refresh_ui() -> tuple[str, InlineKeyboardMarkup]:
        updated_builder = create_notification_settings_keyboard(_, user_specific_settings) # Pass _
        menu_text = _("Notification Settings") # NOTIF_SETTINGS_MENU_HEADER
        return menu_text, updated_builder.as_markup()

    await _process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        _=_,
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
    _: callable, # Changed from language: str
    items: list,
    page: int,
    header_text_source: str, # English source string for header
    empty_list_text_source: str, # English source string for empty list
    keyboard_factory: Callable[..., InlineKeyboardMarkup],
    keyboard_factory_kwargs: dict
) -> None:
    """
    Generic helper to display a paginated list in a Telegram message.
    """
    if not callback_query.message:
        return

    page_slice, total_pages, current_page = _paginate_list(items, page, USERS_PER_PAGE)

    message_parts = [_(header_text_source)] # Corrected _ほぼ to _

    if not items:
        message_parts.append(_(empty_list_text_source))

    page_indicator_text = _("Page {current_page}/{total_pages}").format(current_page=current_page + 1, total_pages=total_pages) # PAGE_INDICATOR
    message_parts.append(f"\n{page_indicator_text}")

    final_message_text = "\n".join(message_parts)

    keyboard_markup = keyboard_factory(
        _=_, # Pass translator
        page_items=page_slice,
        current_page=current_page,
        total_pages=total_pages,
        **keyboard_factory_kwargs
    )

    try:
        await callback_query.message.edit_text(
            text=final_message_text,
            reply_markup=keyboard_markup,
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest in _display_paginated_list for {header_text_source}: {e}", exc_info=True)
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError in _display_paginated_list for {header_text_source}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error in _display_paginated_list for {header_text_source}: {e}", exc_info=True)


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
    _: callable, # Changed from language: str
    user_specific_settings: UserSpecificSettings,
    list_type: str,
    page: int = 0
):
    if not callback_query.message: return

    users_to_process = user_specific_settings.muted_users_set
    sorted_items = sorted(list(users_to_process))

    header_source = "Muted Users (Block List):" if list_type == "muted" else "Allowed Users (Allow List):"
    empty_source = "No users are currently muted." if list_type == "muted" else "No users are currently in the allow list."

    await _display_paginated_list(
        callback_query=callback_query,
        _=_,
        items=sorted_items,
        page=page,
        header_text_source=header_source,
        empty_list_text_source=empty_source,
        keyboard_factory=create_paginated_user_list_keyboard,
        keyboard_factory_kwargs={
            "list_type": list_type,
            "user_specific_settings": user_specific_settings
        }
    )

@callback_router.callback_query(UserListCallback.filter(F.action.in_(["list_muted", "list_allowed"])))
async def cq_list_internal_users(
    callback_query: CallbackQuery,
    # language: str, # REMOVED
    user_specific_settings: UserSpecificSettings,
    callback_data: UserListCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    await callback_query.answer()
    list_type = "muted" if callback_data.action == "list_muted" else "allowed"

    is_mute_all = user_specific_settings.mute_all_flag
    if (list_type == "muted" and is_mute_all) or \
       (list_type == "allowed" and not is_mute_all):
        alert_message_src = "Mute All is ON, showing Allowed list." if is_mute_all else "Mute All is OFF, showing Muted list."
        logger.warning(f"User {callback_query.from_user.id} triggered {callback_data.action} with inconsistent mute_all_flag ({is_mute_all}). Correcting list_type.")
        # Using a generic translated message for inconsistency, specific detail in logs
        await callback_query.answer(_("Displaying appropriate list based on Mute All status."), show_alert=True)
        list_type = "allowed" if is_mute_all else "muted"

    await _display_paginated_user_list(callback_query, _, user_specific_settings, list_type, 0)


@callback_router.callback_query(PaginateUsersCallback.filter(F.list_type.in_(["muted", "allowed"])))
async def cq_paginate_internal_user_list(
    callback_query: CallbackQuery,
    # language: str, # REMOVED
    user_specific_settings: UserSpecificSettings,
    callback_data: PaginateUsersCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    await _display_paginated_user_list(
        callback_query, _, user_specific_settings, callback_data.list_type, callback_data.page
    )


# --- Mute/Unmute from Server Account List Callbacks ---

async def _display_account_list(
    callback_query: CallbackQuery,
    _: callable, # Changed from language: str
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance,
    page: int = 0
):
    if not callback_query.message: return

    if not USER_ACCOUNTS_CACHE:
        try:
            if callback_query.message:
                await callback_query.message.edit_text(_("No user accounts found on the server."))
            else:
                await callback_query.answer(_("No user accounts found on the server."), show_alert=True)
        except TelegramAPIError as e:
            logger.error(f"Error informing user about empty USER_ACCOUNTS_CACHE: {e}")
        return

    all_accounts_tt = list(USER_ACCOUNTS_CACHE.values())
    sorted_items = sorted(
        all_accounts_tt,
        key=lambda acc: ttstr(acc.username).lower()
    )

    await _display_paginated_list(
        callback_query=callback_query,
        _=_,
        items=sorted_items,
        page=page,
        header_text_source="Mute/Unmute - All Server Accounts:",
        empty_list_text_source="No user accounts found on the server.",
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={
            "user_specific_settings": user_specific_settings
        }
    )

@callback_router.callback_query(UserListCallback.filter(F.action == "list_all_accounts"))
async def cq_show_all_accounts_list(
    callback_query: CallbackQuery,
    # language: str, # REMOVED
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance | None,
    callback_data: UserListCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    await callback_query.answer()
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await callback_query.answer(_("TeamTalk bot is not connected. Cannot fetch server users."), show_alert=True)
        return
    await _display_account_list(callback_query, _, user_specific_settings, tt_instance, 0)

@callback_router.callback_query(PaginateUsersCallback.filter(F.list_type == "all_accounts"))
async def cq_paginate_all_accounts_list_action(
    callback_query: CallbackQuery,
    # language: str, # REMOVED
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance | None,
    callback_data: PaginateUsersCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await callback_query.answer(_("TeamTalk bot is not connected. Cannot fetch server users."), show_alert=True)
        return
    await _display_account_list(
        callback_query, _, user_specific_settings, tt_instance, callback_data.page
    )

@callback_router.callback_query(ToggleMuteSpecificCallback.filter(F.action == "toggle_user"))
async def cq_toggle_specific_user_mute_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    # language: str, # REMOVED
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance | None,
    callback_data: ToggleMuteSpecificCallback,
    data: dict[str, Any]
):
    _ = data["_"]
    if not callback_query.message or not callback_query.from_user: return

    user_idx = callback_data.user_idx
    current_page = callback_data.current_page
    list_type = callback_data.list_type

    username_to_toggle: str | None = None
    display_nickname_for_toast: str | None = None

    if list_type == "all_accounts":
        if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
            await callback_query.answer(_("TeamTalk bot is not connected. Cannot fetch server users."), show_alert=True) # TT_BOT_NOT_CONNECTED_FOR_LIST
            return
        try:
            all_accounts_tt = list(USER_ACCOUNTS_CACHE.values())
            sorted_accounts = sorted(all_accounts_tt, key=lambda acc: ttstr(acc._account.szUsername).lower())
            start_index = current_page * USERS_PER_PAGE
            current_page_items = sorted_accounts[start_index : start_index + USERS_PER_PAGE]
            if 0 <= user_idx < len(current_page_items):
                target_account = current_page_items[user_idx]
                username_to_toggle = ttstr(target_account._account.szUsername)
                display_nickname_for_toast = username_to_toggle
            else:
                logger.warning(f"Invalid user_idx {user_idx} for all_accounts list page {current_page}.")
        except Exception as e:
            logger.error(f"Error retrieving account for toggle: {e}")
            await callback_query.answer(_("An error occurred."), show_alert=True) # error_occurred
            return
    elif list_type in ["muted", "allowed"]:
        relevant_set = user_specific_settings.muted_users_set
        sorted_list_usernames = sorted(list(relevant_set))
        start_index = current_page * USERS_PER_PAGE
        current_page_items = sorted_list_usernames[start_index : start_index + USERS_PER_PAGE]
        if 0 <= user_idx < len(current_page_items):
            username_to_toggle = current_page_items[user_idx]
            display_nickname_for_toast = username_to_toggle
        else:
            logger.warning(f"Invalid user_idx {user_idx} for {list_type} list page {current_page}.")
    else:
        logger.error(f"Unknown list_type '{list_type}' in cq_toggle_specific_user_mute_action.")
        await callback_query.answer(_("Error: Unknown list type."), show_alert=True)
        return

    if not username_to_toggle or not display_nickname_for_toast:
        logger.error(f"Could not determine username for toggle. user_idx: {user_idx}, list_type: {list_type}, page: {current_page}")
        await callback_query.answer(_("An error occurred."), show_alert=True) # error_occurred
        # Refresh logic based on list_type
        if list_type == "all_accounts" and tt_instance and tt_instance.connected:
             await _display_account_list(callback_query, _, user_specific_settings, tt_instance, 0)
        elif list_type in ["muted", "allowed"]:
             await _display_paginated_user_list(callback_query, _, user_specific_settings, list_type, 0)
        return

    if username_to_toggle in user_specific_settings.muted_users_set:
        user_specific_settings.muted_users_set.discard(username_to_toggle)
    else:
        user_specific_settings.muted_users_set.add(username_to_toggle)

    is_mute_all_active = user_specific_settings.mute_all_flag
    effectively_muted_after_toggle = (is_mute_all_active and username_to_toggle not in user_specific_settings.muted_users_set) or \
                                     (not is_mute_all_active and username_to_toggle in user_specific_settings.muted_users_set)

    status_for_toast = _("Muted") if effectively_muted_after_toggle else _("Not Muted") # MUTED_STATUS, NOT_MUTED_STATUS

    # Use specific toasts for muted/allowed lists for clarity
    if list_type == "muted" or list_type == "allowed":
         toast_message = _("{username} has been unmuted.").format(username=html.quote(display_nickname_for_toast)) if not effectively_muted_after_toggle else _("{username} has been muted.").format(username=html.quote(display_nickname_for_toast)) # USER_UNMUTED_TOAST, USER_MUTED_TOAST
    else: # For all_accounts list
         toast_message = _("Mute status for {username} is now {status}.").format(username=html.quote(display_nickname_for_toast), status=status_for_toast) # USER_MUTE_STATUS_UPDATED_TOAST

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_specific_settings)
        await callback_query.answer(toast_message, show_alert=False)
    except Exception as e:
        logger.error(f"DB error or answer error in toggle_user for {username_to_toggle}: {e}")
        if username_to_toggle in user_specific_settings.muted_users_set: # Revert in-memory change
            user_specific_settings.muted_users_set.discard(username_to_toggle)
        else:
            user_specific_settings.muted_users_set.add(username_to_toggle)
        try:
            await callback_query.answer(_("An error occurred."), show_alert=True) # error_occurred
        except TelegramAPIError: pass
        return

    if list_type == "all_accounts":
        if tt_instance and tt_instance.connected:
            await _display_account_list(callback_query, _, user_specific_settings, tt_instance, current_page)
        else:
            await callback_query.answer(_("TeamTalk bot is not connected. Cannot fetch server users."), show_alert=True) # TT_BOT_NOT_CONNECTED_FOR_LIST
            # Pass data with _ to cq_show_manage_muted_menu
            await cq_show_manage_muted_menu(callback_query, user_specific_settings=user_specific_settings, callback_data=NotificationActionCallback(action="manage_muted"), data=data)

    elif list_type in ["muted", "allowed"]:
        await _display_paginated_user_list(callback_query, _, user_specific_settings, list_type, current_page)
    else:
        logger.error(f"Unknown list_type '{list_type}' for refresh in cq_toggle_specific_user_mute_action")
        await callback_query.answer(_("Error: Could not refresh list due to unknown list type."), show_alert=True)
