# bot/telegram_bot/handlers/callback_handlers/mute.py

import logging
import math
from typing import Callable, Any, Optional
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk
from pytalk.instance import TeamTalkInstance

from bot.core.user_settings import UserSpecificSettings, update_user_settings_in_db
from bot.telegram_bot.keyboards import (
    create_manage_muted_users_keyboard,
    create_paginated_user_list_keyboard,
    create_account_list_keyboard,
)
from bot.telegram_bot.callback_data import (
    NotificationActionCallback,
    MuteAllCallback,
    UserListCallback,
    PaginateUsersCallback,
    ToggleMuteSpecificCallback,
)
from bot.core.enums import (
    NotificationAction,
    MuteAllAction,
    UserListAction,
    # PaginateUsersAction, # Not directly used for filtering here, list_type is UserListAction
    ToggleMuteSpecificAction
)
from bot.constants import USERS_PER_PAGE
from bot.state import USER_ACCOUNTS_CACHE
from ._helpers import process_setting_update

logger = logging.getLogger(__name__)
mute_router = Router(name="callback_handlers.mute")
ttstr = pytalk.instance.sdk.ttstr


def _paginate_list_util(full_list: list, page: int, page_size: int) -> tuple[list, int, int]:
    total_items = len(full_list)
    total_pages = int(math.ceil(total_items / page_size)) if total_items > 0 else 1
    page = max(0, min(page, total_pages - 1))
    start_index = page * page_size
    end_index = start_index + page_size
    page_slice = full_list[start_index:end_index]
    return page_slice, total_pages, page


async def _display_paginated_list_ui(
    callback_query: CallbackQuery,
    _: callable,
    items: list,
    page: int,
    header_text_key: str,
    empty_list_text_key: str,
    keyboard_factory: Callable[..., InlineKeyboardMarkup],
    keyboard_factory_kwargs: dict,
) -> None:
    if not callback_query.message:
        return

    page_slice, total_pages, current_page_idx = _paginate_list_util(items, page, USERS_PER_PAGE)

    message_parts = [_(header_text_key)] # Apply translation to header key
    if not items:
        message_parts.append(_(empty_list_text_key))

    page_indicator_text = _("Page {current_page}/{total_pages}").format(
        current_page=current_page_idx + 1, total_pages=total_pages
    )
    message_parts.append(f"\n{page_indicator_text}")

    final_message_text = "\n".join(message_parts)

    keyboard_markup = keyboard_factory(
        _=_, page_items=page_slice, current_page=current_page_idx, total_pages=total_pages, **keyboard_factory_kwargs
    )

    try:
        await callback_query.message.edit_text(text=final_message_text, reply_markup=keyboard_markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest in _display_paginated_list_ui for {header_text_key}: {e}", exc_info=True)
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError in _display_paginated_list_ui for {header_text_key}: {e}", exc_info=True)


async def _display_internal_user_list(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    list_type: UserListAction,
    page: int = 0,
):
    if not callback_query.message:
        return

    users_to_process = user_specific_settings.muted_users_set
    sorted_items = sorted(list(users_to_process))
    # is_mute_all_active = user_specific_settings.mute_all_flag # Not directly used here, but influences list_type meaning

    header_key, empty_key = "", ""
    if list_type == UserListAction.LIST_MUTED:
        header_key = "MUTED_USERS_HEADER"
        empty_key = "NO_MUTED_USERS_TEXT"
    elif list_type == UserListAction.LIST_ALLOWED:
        header_key = "ALLOWED_USERS_HEADER"
        empty_key = "NO_ALLOWED_USERS_TEXT"
    else: # Should not happen if called with UserListAction members
        logger.error(f"Unknown list_type '{list_type.value if isinstance(list_type, UserListAction) else list_type}' in _display_internal_user_list")
        await callback_query.answer(_("GENERIC_ERROR_TEXT"), show_alert=True)
        return

    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_,
        items=sorted_items,
        page=page,
        header_text_key=header_key, # _display_paginated_list_ui will call _() on this key
        empty_list_text_key=empty_key,
        keyboard_factory=create_paginated_user_list_keyboard,
        keyboard_factory_kwargs={"list_type": list_type, "user_specific_settings": user_specific_settings},
    )


async def _display_all_server_accounts_list(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    tt_instance: TeamTalkInstance, # Optionality handled by caller
    page: int = 0,
):
    if not callback_query.message:
        return

    if not USER_ACCOUNTS_CACHE:
        try:
            await callback_query.message.edit_text(_("SERVER_ACCOUNTS_NOT_LOADED_TEXT"))
        except TelegramAPIError as e:
            logger.error(f"Error informing user about empty USER_ACCOUNTS_CACHE: {e}")
        return

    all_accounts_tt = list(USER_ACCOUNTS_CACHE.values())
    sorted_items = sorted(all_accounts_tt, key=lambda acc: ttstr(acc.username).lower())

    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_,
        items=sorted_items,
        page=page,
        header_text_key="ALL_SERVER_ACCOUNTS_HEADER", # _display_paginated_list_ui will call _() on this key
        empty_list_text_key="NO_SERVER_ACCOUNTS_TEXT",
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={"user_specific_settings": user_specific_settings},
    )


def _get_username_to_toggle_from_callback(
    callback_data: ToggleMuteSpecificCallback, user_specific_settings: UserSpecificSettings
) -> Optional[str]:
    """Extracts the username to be toggled from the callback data based on the list type."""
    user_idx = callback_data.user_idx
    current_page = callback_data.current_page
    list_type = callback_data.list_type # This is already UserListAction

    if list_type == UserListAction.LIST_ALL_ACCOUNTS:
        if not USER_ACCOUNTS_CACHE:
            logger.warning("Attempted to get username from 'all_accounts' list, but USER_ACCOUNTS_CACHE is empty.")
            return None
        all_accounts = sorted(list(USER_ACCOUNTS_CACHE.values()), key=lambda acc: ttstr(acc.username).lower())
        page_items, _, _ = _paginate_list_util(all_accounts, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            return ttstr(page_items[user_idx].username)
    elif list_type in [UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]:
        # This list always comes from muted_users_set, regardless of mute_all_flag
        # The interpretation of what this list means (muted or allowed) happens at a higher level
        relevant_usernames = sorted(list(user_specific_settings.muted_users_set))
        page_items, _, _ = _paginate_list_util(relevant_usernames, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            return page_items[user_idx]

    logger.warning(f"Could not find username for toggle. Idx: {user_idx}, List: {list_type.value if isinstance(list_type, UserListAction) else list_type}, Page: {current_page}")
    return None


def _parse_mute_toggle_callback_data(
    callback_data: ToggleMuteSpecificCallback, user_specific_settings: UserSpecificSettings
) -> Optional[str]:
    """
    Parses the callback data to get the username to toggle.
    This is a wrapper around _get_username_to_toggle_from_callback.
    """
    return _get_username_to_toggle_from_callback(callback_data, user_specific_settings)


def _determine_mute_action_and_update_settings(
    username_to_toggle: str, user_specific_settings: UserSpecificSettings
) -> tuple[str, bool, set[str]]:
    """
    Determines the mute action, updates settings in-memory, and returns original settings.
    """
    original_muted_users_set = set(user_specific_settings.muted_users_set)
    action_taken: str
    current_status_is_muted: bool  # Is the user considered muted *before* this toggle action

    if user_specific_settings.mute_all_flag:
        # Mute all ON: muted_users_set = allowed users
        if username_to_toggle in user_specific_settings.muted_users_set:  # Was allowed
            user_specific_settings.muted_users_set.discard(username_to_toggle)  # Now not allowed
            action_taken = "removed_from_allowed_list"
            current_status_is_muted = False  # Was allowed (so, not muted)
        else:
            user_specific_settings.muted_users_set.add(username_to_toggle)  # Now allowed
            action_taken = "added_to_allowed_list"
            current_status_is_muted = True  # Was not in allowed list (so, effectively muted by mute_all)
    else:
        # Mute all OFF: muted_users_set = muted users
        if username_to_toggle in user_specific_settings.muted_users_set:  # Was muted
            user_specific_settings.muted_users_set.discard(username_to_toggle)  # Now not muted
            action_taken = "removed_from_muted_list"
            current_status_is_muted = True  # Was muted
        else:
            user_specific_settings.muted_users_set.add(username_to_toggle)  # Now muted
            action_taken = "added_to_muted_list"
            current_status_is_muted = False  # Was not muted

    return action_taken, current_status_is_muted, original_muted_users_set


def _generate_mute_toggle_toast_message(
    username_to_toggle: str,
    new_status_is_muted: bool, # True if muted AFTER toggle, False if unmuted AFTER toggle
    mute_all_flag: bool, # Current state of user_specific_settings.mute_all_flag
    _: callable
) -> str:
    """Generates the toast message for the mute toggle action."""
    quoted_username = html.quote(username_to_toggle)
    status_text_key: str

    if new_status_is_muted:
        # If mute_all_flag is True, it means the user is now effectively muted because they are NOT in the allowed list (for mute_all scenario)
        # OR they are explicitly in the muted list (for not mute_all scenario)
        status_text_key = "USER_STATUS_NOW_MUTED_BY_MUTE_ALL" if mute_all_flag else "USER_STATUS_NOW_MUTED"
    else: # New status is unmuted
        # If mute_all_flag is True, it means the user is now unmuted because they ARE in the allowed list
        # If mute_all_flag is False, it means the user is now unmuted because they are NOT in the muted list
        status_text_key = "USER_STATUS_NOW_ALLOWED" if mute_all_flag else "USER_STATUS_NOW_UNMUTED"

    return _("USER_MUTE_STATUS_UPDATED_TOAST").format(username=quoted_username, status=_(status_text_key))


async def _save_mute_settings_and_notify(
    session: AsyncSession,
    callback_query: CallbackQuery,
    user_settings: UserSpecificSettings, # This is user_specific_settings in the main handler
    toast_message: str,
    username_to_toggle: str, # For logging
    action_taken: str, # For logging
    original_muted_users_set: set[str],
    _: callable
) -> bool:
    """
    Saves mute settings to DB, sends toast notification, and handles errors/reverts.
    Returns True if successful, False otherwise.
    """
    if not callback_query.from_user: # Should be checked by caller, but as a safeguard
        logger.error("Cannot save settings: callback_query.from_user is None.")
        await callback_query.answer(_("GENERIC_ERROR_TEXT"), show_alert=True)
        return False

    try:
        await update_user_settings_in_db(session, callback_query.from_user.id, user_settings)
        await callback_query.answer(toast_message, show_alert=False)
        return True
    except Exception as e:
        logger.error(f"DB/Answer error for {username_to_toggle} (action: {action_taken}): {e}", exc_info=True)
        user_settings.muted_users_set = original_muted_users_set  # Revert in-memory change
        await callback_query.answer(_("GENERIC_ERROR_TEXT"), show_alert=True)
        return False


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: ToggleMuteSpecificCallback # Contains list_type and current_page
) -> None:
    """Refreshes the mute-related UI list after a toggle action."""
    list_type_user_was_on = callback_data.list_type
    current_page_for_refresh = callback_data.current_page

    if list_type_user_was_on == UserListAction.LIST_ALL_ACCOUNTS:
        if tt_instance and tt_instance.connected and tt_instance.logged_in:
            await _display_all_server_accounts_list(callback_query, _, user_specific_settings, tt_instance, current_page_for_refresh)
        else:
            # This toast might be overridden by the one in _save_mute_settings_and_notify if that one fails
            # However, if saving succeeds but TT is disconnected for UI refresh, this is important.
            await callback_query.answer(_("TT_BOT_DISCONNECTED_REFRESH_FAILED_TOAST"), show_alert=True)
            # Fallback to the main mute menu
            manage_muted_cb_data = NotificationActionCallback(action=NotificationAction.MANAGE_MUTED)
            # We don't need to pass specific callback_data for MANAGE_MUTED action itself,
            # as cq_show_manage_muted_menu doesn't use specific fields from it for its core logic.
            await cq_show_manage_muted_menu(callback_query, _, user_specific_settings, manage_muted_cb_data)
    else:  # LIST_MUTED or LIST_ALLOWED
        # _display_internal_user_list correctly derives the effective list to show
        # based on user_specific_settings.mute_all_flag and the list_type_user_was_on.
        await _display_internal_user_list(callback_query, _, user_specific_settings, list_type_user_was_on, current_page_for_refresh)


@mute_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.MANAGE_MUTED))
async def cq_show_manage_muted_menu(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    callback_data: NotificationActionCallback, # This argument is not used by the function body
):
    if not callback_query.message:
        await callback_query.answer(_("Error: No message associated with callback."))
        return
    await callback_query.answer()
    manage_muted_builder = create_manage_muted_users_keyboard(_, user_specific_settings)
    try:
        await callback_query.message.edit_text(text=_("MANAGE_MUTED_MENU_HEADER"), reply_markup=manage_muted_builder.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for manage_muted_users menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for manage_muted_users menu: {e}")


@mute_router.callback_query(MuteAllCallback.filter(F.action == MuteAllAction.TOGGLE_MUTE_ALL))
async def cq_toggle_mute_all_action(
    callback_query: CallbackQuery, session: AsyncSession, _: callable, user_specific_settings: UserSpecificSettings, callback_data: MuteAllCallback # This argument is not used by the function body
):
    if not callback_query.message or not callback_query.from_user:
        await callback_query.answer(_("Error: Missing data for Mute All toggle."), show_alert=True)
        return

    original_flag = user_specific_settings.mute_all_flag

    def update_logic():
        user_specific_settings.mute_all_flag = not original_flag

    def revert_logic():
        user_specific_settings.mute_all_flag = original_flag

    new_status_text_key = "ENABLED_STATUS" if not original_flag else "DISABLED_STATUS"
    new_status_display_text = _(new_status_text_key)
    success_toast_text = _("MUTE_ALL_UPDATED_TO").format(status=new_status_display_text)

    def refresh_ui_callable() -> tuple[str, InlineKeyboardMarkup]:
        updated_builder = create_manage_muted_users_keyboard(_, user_specific_settings)
        menu_text = _("MANAGE_MUTED_MENU_HEADER")
        return menu_text, updated_builder.as_markup()

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_specific_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        ui_refresh_callable=refresh_ui_callable,
    )


@mute_router.callback_query(UserListCallback.filter(F.action.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_list_internal_users_action(
    callback_query: CallbackQuery, _: callable, user_specific_settings: UserSpecificSettings, callback_data: UserListCallback
):
    await callback_query.answer()
    requested_list_type = callback_data.action # This is now a UserListAction member
    is_mute_all_active = user_specific_settings.mute_all_flag

    # Determine the actual list type to display based on mute_all_flag
    effective_list_type = requested_list_type
    if is_mute_all_active:
        if requested_list_type == UserListAction.LIST_MUTED:
            effective_list_type = UserListAction.LIST_ALLOWED
        # if requested_list_type == UserListAction.LIST_ALLOWED, it remains UserListAction.LIST_ALLOWED
    else: # mute_all is OFF
        if requested_list_type == UserListAction.LIST_ALLOWED:
            effective_list_type = UserListAction.LIST_MUTED
        # if requested_list_type == UserListAction.LIST_MUTED, it remains UserListAction.LIST_MUTED

    await _display_internal_user_list(callback_query, _, user_specific_settings, effective_list_type, 0)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery, _: callable, user_specific_settings: UserSpecificSettings, callback_data: PaginateUsersCallback
):
    await callback_query.answer()
    # callback_data.list_type is already UserListAction from CallbackData definition
    await _display_internal_user_list(callback_query, _, user_specific_settings, callback_data.list_type, callback_data.page)


@mute_router.callback_query(UserListCallback.filter(F.action == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_show_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: UserListCallback, # This argument is not used by the function body
):
    await callback_query.answer()
    if not callback_query.message: return
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await callback_query.message.edit_text(_("TT_BOT_NOT_CONNECTED_FOR_USERS_TEXT"))
        return
    if not USER_ACCOUNTS_CACHE:
        # Try to edit, but if it fails (e.g. message deleted), it's okay, just log.
        try: await callback_query.message.edit_text(_("NO_SERVER_ACCOUNTS_LOADED_TEXT"))
        except TelegramAPIError as e: logger.warning(f"Failed to edit message for NO_SERVER_ACCOUNTS_LOADED_TEXT: {e}")
        return
    await _display_all_server_accounts_list(callback_query, _, user_specific_settings, tt_instance, 0)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_paginate_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: PaginateUsersCallback,
):
    await callback_query.answer()
    if not callback_query.message: return
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await callback_query.message.edit_text(_("TT_BOT_NOT_CONNECTED_FOR_USERS_TEXT"))
        return
    if not USER_ACCOUNTS_CACHE:
        try: await callback_query.message.edit_text(_("NO_SERVER_ACCOUNTS_LOADED_TEXT"))
        except TelegramAPIError as e: logger.warning(f"Failed to edit message for NO_SERVER_ACCOUNTS_LOADED_TEXT on paginate: {e}")
        return
    await _display_all_server_accounts_list(callback_query, _, user_specific_settings, tt_instance, callback_data.page)


@mute_router.callback_query(ToggleMuteSpecificCallback.filter(F.action == ToggleMuteSpecificAction.TOGGLE_USER))
async def cq_toggle_specific_user_mute_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_specific_settings: UserSpecificSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: ToggleMuteSpecificCallback,
):
    if not callback_query.message or not callback_query.from_user:
        # If no message or user, cannot proceed. Answer silently or log if needed.
        # Consider await callback_query.answer() if appropriate, but often not needed if no user interaction.
        return

    username_to_toggle = _parse_mute_toggle_callback_data(callback_data, user_specific_settings)

    if not username_to_toggle:
        await callback_query.answer(_("GENERIC_ERROR_TEXT"), show_alert=True)
        return

    action_taken, current_status_is_muted, original_muted_users_set = \
        _determine_mute_action_and_update_settings(username_to_toggle, user_specific_settings)

    new_status_is_muted = not current_status_is_muted # Status *after* the toggle

    toast_message = _generate_mute_toggle_toast_message(
        username_to_toggle,
        new_status_is_muted,
        user_specific_settings.mute_all_flag,
        _
    )

    save_successful = await _save_mute_settings_and_notify(
        session,
        callback_query,
        user_specific_settings,
        toast_message,
        username_to_toggle,
        action_taken,
        original_muted_users_set,
        _
    )

    if not save_successful:
        # Error handling (toast, revert) already done in _save_mute_settings_and_notify
        return

    # If save was successful, proceed to refresh UI
    await _refresh_mute_related_ui(
        callback_query,
        _,
        user_specific_settings,
        tt_instance,
        callback_data
    )
