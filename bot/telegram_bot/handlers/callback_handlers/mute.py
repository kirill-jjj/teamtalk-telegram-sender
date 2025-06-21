import logging
import math
from typing import Callable, Any, Optional
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk
from pytalk.instance import TeamTalkInstance

from bot.models import UserSettings
from bot.core.user_settings import (
    update_user_settings_in_db,
    get_muted_users_set,
    set_muted_users_from_set
)
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
    page_slice, total_pages, current_page_idx = _paginate_list_util(items, page, USERS_PER_PAGE)

    message_parts = [_(header_text_key)]
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
    user_settings: UserSettings,
    list_type: UserListAction,
    page: int = 0,
):
    users_to_process = get_muted_users_set(user_settings)
    sorted_items = sorted(list(users_to_process))

    header_text, empty_list_text = "", ""
    if list_type == UserListAction.LIST_MUTED:
        header_text = _("Muted Users (Block List)")
        empty_list_text = _("You haven't muted anyone yet.")
    elif list_type == UserListAction.LIST_ALLOWED:
        header_text = _("Allowed Users (Allow List)")
        empty_list_text = _("No users are currently on the allow list.")
    else: # Should not happen if called with UserListAction members
        logger.error(f"Unknown list_type '{list_type.value if isinstance(list_type, UserListAction) else list_type}' in _display_internal_user_list")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    # Note: _display_paginated_list_ui expects keys, so we pass the translated strings directly
    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_, # _ is still needed by _display_paginated_list_ui for "Page x/y"
        items=sorted_items,
        page=page,
        header_text_key=header_text,
        empty_list_text_key=empty_list_text,
        keyboard_factory=create_paginated_user_list_keyboard,
        keyboard_factory_kwargs={"list_type": list_type, "user_settings": user_settings},
    )


async def _display_all_server_accounts_list(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_instance: TeamTalkInstance, # Optionality handled by caller
    page: int = 0,
):
    if not USER_ACCOUNTS_CACHE:
        try:
            await callback_query.message.edit_text(_("Server user accounts are not loaded yet. Please try again in a moment."))
        except TelegramAPIError as e:
            logger.error(f"Error informing user about empty USER_ACCOUNTS_CACHE: {e}")
        return

    all_accounts_tt = list(USER_ACCOUNTS_CACHE.values())
    sorted_items = sorted(all_accounts_tt, key=lambda acc: ttstr(acc.username).lower())

    # Note: _display_paginated_list_ui expects keys, so we pass the translated strings directly
    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_, # _ is still needed by _display_paginated_list_ui for "Page x/y"
        items=sorted_items,
        page=page,
        header_text_key=_("All Server Accounts"),
        empty_list_text_key=_("No user accounts found on the server."),
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={"user_settings": user_settings},
    )


def _get_username_to_toggle_from_callback(
    callback_data: ToggleMuteSpecificCallback, user_settings: UserSettings
) -> Optional[str]:
    """Extracts the username to be toggled from the callback data based on the list type."""
    user_idx = callback_data.user_idx
    current_page = callback_data.current_page
    list_type = callback_data.list_type

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
        relevant_usernames = sorted(list(get_muted_users_set(user_settings)))
        page_items, _, _ = _paginate_list_util(relevant_usernames, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            return page_items[user_idx]

    logger.warning(f"Could not find username for toggle. Idx: {user_idx}, List: {list_type.value if isinstance(list_type, UserListAction) else list_type}, Page: {current_page}")
    return None


def _parse_mute_toggle_callback_data(
    callback_data: ToggleMuteSpecificCallback, user_settings: UserSettings
) -> Optional[str]:
    """
    Parses the callback data to get the username to toggle.
    This is a wrapper around _get_username_to_toggle_from_callback.
    """
    return _get_username_to_toggle_from_callback(callback_data, user_settings)


def _determine_mute_action_and_update_settings(
    username_to_toggle: str, user_settings: UserSettings
) -> tuple[str, bool, set[str]]:
    """
    Determines the mute action, updates settings in-memory, and returns original settings.
    """
    current_muted_set = get_muted_users_set(user_settings)
    original_muted_users_set = set(current_muted_set) # Make a copy
    action_taken: str
    current_status_is_muted: bool  # Is the user considered muted *before* this toggle action

    if user_settings.mute_all:
        # Mute all ON: current_muted_set = allowed users
        if username_to_toggle in current_muted_set:
            current_muted_set.discard(username_to_toggle)
            action_taken = "removed_from_allowed_list"
            current_status_is_muted = False # Was allowed, now muted by MuteAll
        else:
            current_muted_set.add(username_to_toggle)
            action_taken = "added_to_allowed_list"
            current_status_is_muted = True # Was muted by MuteAll, now allowed
    else:
        # Mute all OFF: current_muted_set = muted users
        if username_to_toggle in current_muted_set:
            current_muted_set.discard(username_to_toggle)
            action_taken = "removed_from_muted_list"
            current_status_is_muted = True # Was muted, now unmuted
        else:
            current_muted_set.add(username_to_toggle)
            action_taken = "added_to_muted_list"
            current_status_is_muted = False # Was unmuted, now muted

    set_muted_users_from_set(user_settings, current_muted_set)
    return action_taken, current_status_is_muted, original_muted_users_set


def _generate_mute_toggle_toast_message(
    username_to_toggle: str,
    new_status_is_muted: bool, # True if muted AFTER toggle, False if unmuted AFTER toggle
    mute_all_flag: bool, # Current state of user_specific_settings.mute_all_flag
    _: callable
) -> str:
    """Generates the toast message for the mute toggle action."""
    quoted_username = html.quote(username_to_toggle)
    status_text: str

    if new_status_is_muted:
        status_text = _("muted (due to Mute All mode)") if mute_all_flag else _("muted")
    else:
        status_text = _("allowed (in Mute All mode)") if mute_all_flag else _("unmuted")

    return _("{username} is now {status}.").format(username=quoted_username, status=status_text)


async def _save_mute_settings_and_notify(
    session: AsyncSession,
    callback_query: CallbackQuery,
    user_settings: UserSettings,
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
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return False

    try:
        await update_user_settings_in_db(session, user_settings)
        await callback_query.answer(toast_message, show_alert=False)
        return True
    except Exception as e:
        logger.error(f"DB/Answer error for {username_to_toggle} (action: {action_taken}): {e}", exc_info=True)
        set_muted_users_from_set(user_settings, original_muted_users_set)
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return False


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: ToggleMuteSpecificCallback # Contains list_type and current_page
) -> None:
    """Refreshes the mute-related UI list after a toggle action."""
    list_type_user_was_on = callback_data.list_type
    current_page_for_refresh = callback_data.current_page

    if list_type_user_was_on == UserListAction.LIST_ALL_ACCOUNTS:
        if tt_instance and tt_instance.connected and tt_instance.logged_in:
            await _display_all_server_accounts_list(callback_query, _, user_settings, tt_instance, current_page_for_refresh)
        else:
            # This toast might be overridden by the one in _save_mute_settings_and_notify if that one fails
            # However, if saving succeeds but TT is disconnected for UI refresh, this is important.
            await callback_query.answer(_("TeamTalk bot is disconnected. UI could not be refreshed."), show_alert=True)
            # Fallback to the main mute menu
            manage_muted_cb_data = NotificationActionCallback(action=NotificationAction.MANAGE_MUTED)
            # We don't need to pass specific callback_data for MANAGE_MUTED action itself,
            # as cq_show_manage_muted_menu doesn't use specific fields from it for its core logic.
            await cq_show_manage_muted_menu(callback_query, _, user_settings, manage_muted_cb_data)
    else:  # LIST_MUTED or LIST_ALLOWED
        # _display_internal_user_list correctly derives the effective list to show
        # based on user_settings.mute_all and the list_type_user_was_on.
        await _display_internal_user_list(callback_query, _, user_settings, list_type_user_was_on, current_page_for_refresh)


@mute_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.MANAGE_MUTED))
async def cq_show_manage_muted_menu(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    callback_data: NotificationActionCallback,
):
    await callback_query.answer()
    manage_muted_builder = create_manage_muted_users_keyboard(_, user_settings)
    try:
        await callback_query.message.edit_text(text=_("Manage Muted/Allowed Users"), reply_markup=manage_muted_builder.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"TelegramBadRequest editing message for manage_muted_users menu: {e}")
    except TelegramAPIError as e:
        logger.error(f"TelegramAPIError editing message for manage_muted_users menu: {e}")


@mute_router.callback_query(MuteAllCallback.filter(F.action == MuteAllAction.TOGGLE_MUTE_ALL))
async def cq_toggle_mute_all_action(
    callback_query: CallbackQuery, session: AsyncSession, _: callable, user_settings: UserSettings, callback_data: MuteAllCallback
):
    original_flag = user_settings.mute_all

    def update_logic():
        user_settings.mute_all = not original_flag

    def revert_logic():
        user_settings.mute_all = original_flag

    new_status_display_text = _("Enabled") if not original_flag else _("Disabled")
    success_toast_text = _("Mute All mode is now {status}.").format(status=new_status_display_text)

    def refresh_ui_callable() -> tuple[str, InlineKeyboardMarkup]:
        updated_builder = create_manage_muted_users_keyboard(_, user_settings)
        menu_text = _("Manage Muted/Allowed Users")
        return menu_text, updated_builder.as_markup()

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=user_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        ui_refresh_callable=refresh_ui_callable,
    )


@mute_router.callback_query(UserListCallback.filter(F.action.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_list_internal_users_action(
    callback_query: CallbackQuery, _: callable, user_settings: UserSettings, callback_data: UserListCallback
):
    await callback_query.answer()
    requested_list_type = callback_data.action # This is now a UserListAction member
    is_mute_all_active = user_settings.mute_all

    effective_list_type = requested_list_type
    if is_mute_all_active:
        if requested_list_type == UserListAction.LIST_MUTED:
            effective_list_type = UserListAction.LIST_ALLOWED
        # if requested_list_type == UserListAction.LIST_ALLOWED, it remains UserListAction.LIST_ALLOWED
    else: # mute_all is OFF
        if requested_list_type == UserListAction.LIST_ALLOWED:
            effective_list_type = UserListAction.LIST_MUTED
        # if requested_list_type == UserListAction.LIST_MUTED, it remains UserListAction.LIST_MUTED

    await _display_internal_user_list(callback_query, _, user_settings, effective_list_type, 0)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery, _: callable, user_settings: UserSettings, callback_data: PaginateUsersCallback
):
    await callback_query.answer()
    # callback_data.list_type is already UserListAction from CallbackData definition
    await _display_internal_user_list(callback_query, _, user_settings, callback_data.list_type, callback_data.page)


@mute_router.callback_query(UserListCallback.filter(F.action == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_show_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: UserListCallback,
):
    await callback_query.answer()
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await callback_query.message.edit_text(_("TeamTalk bot is not connected. Cannot display user list."))
        return
    if not USER_ACCOUNTS_CACHE:
        # Try to edit, but if it fails (e.g. message deleted), it's okay, just log.
        try: await callback_query.message.edit_text(_("Server user accounts have not been loaded yet. Please try again in a moment."))
        except TelegramAPIError as e: logger.warning(f"Failed to edit message for NO_SERVER_ACCOUNTS_LOADED_TEXT: {e}")
        return
    await _display_all_server_accounts_list(callback_query, _, user_settings, tt_instance, 0)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_paginate_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: PaginateUsersCallback,
):
    await callback_query.answer()
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await callback_query.message.edit_text(_("TeamTalk bot is not connected. Cannot display user list."))
        return
    if not USER_ACCOUNTS_CACHE:
        try: await callback_query.message.edit_text(_("Server user accounts have not been loaded yet. Please try again in a moment."))
        except TelegramAPIError as e: logger.warning(f"Failed to edit message for NO_SERVER_ACCOUNTS_LOADED_TEXT on paginate: {e}")
        return
    await _display_all_server_accounts_list(callback_query, _, user_settings, tt_instance, callback_data.page)


@mute_router.callback_query(ToggleMuteSpecificCallback.filter(F.action == ToggleMuteSpecificAction.TOGGLE_USER))
async def cq_toggle_specific_user_mute_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: ToggleMuteSpecificCallback,
):
    username_to_toggle = _parse_mute_toggle_callback_data(callback_data, user_settings)

    if not username_to_toggle:
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    action_taken, current_status_is_muted, original_muted_users_set = \
        _determine_mute_action_and_update_settings(username_to_toggle, user_settings)

    new_status_is_muted = not current_status_is_muted

    toast_message = _generate_mute_toggle_toast_message(
        username_to_toggle,
        new_status_is_muted,
        user_settings.mute_all,
        _
    )

    save_successful = await _save_mute_settings_and_notify(
        session,
        callback_query,
        user_settings,
        toast_message,
        username_to_toggle,
        action_taken,
        original_muted_users_set,
        _
    )

    if not save_successful:
        return

    await _refresh_mute_related_ui(
        callback_query,
        _,
        user_settings,
        tt_instance,
        callback_data
    )
