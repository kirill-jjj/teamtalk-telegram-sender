import logging
import math
from typing import Callable, Any, Optional
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete # Added select, delete

import pytalk
from pytalk.instance import TeamTalkInstance

from bot.models import UserSettings, MutedUser # Added MutedUser
from bot.core.user_settings import (
    update_user_settings_in_db,
    # get_muted_users_set, # Removed
    # set_muted_users_from_set # Removed
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
    list_type: UserListAction, # This will determine the header and empty text
    page: int = 0,
    session: Optional[AsyncSession] = None, # Added session for DB query
):
    if not session: # Should be provided by the caller
        logger.error("Session not provided to _display_internal_user_list")
        await callback_query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    # Query MutedUser table directly
    statement = select(MutedUser.muted_teamtalk_username).where(MutedUser.user_settings_telegram_id == user_settings.telegram_id)
    results = await session.execute(statement)
    # users_to_process will be a list of usernames (str)
    users_to_process = results.scalars().all()
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


async def _get_username_to_toggle_from_callback( # Made async
    callback_data: ToggleMuteSpecificCallback, user_settings: UserSettings, session: AsyncSession # Added session
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
        # Query MutedUser table directly
        statement = select(MutedUser.muted_teamtalk_username).where(MutedUser.user_settings_telegram_id == user_settings.telegram_id)
        results = await session.execute(statement)
        relevant_usernames = sorted(list(results.scalars().all()))
        page_items, _, _ = _paginate_list_util(relevant_usernames, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            return page_items[user_idx]

    logger.warning(f"Could not find username for toggle. Idx: {user_idx}, List: {list_type.value if isinstance(list_type, UserListAction) else list_type}, Page: {current_page}")
    return None


async def _parse_mute_toggle_callback_data( # Made async
    callback_data: ToggleMuteSpecificCallback, user_settings: UserSettings, session: AsyncSession # Added session
) -> Optional[str]:
    """
    Parses the callback data to get the username to toggle.
    This is a wrapper around _get_username_to_toggle_from_callback.
    """
    return await _get_username_to_toggle_from_callback(callback_data, user_settings, session) # Added await and session


async def _determine_mute_action_and_update_settings( # Made async
    username_to_toggle: str, user_settings: UserSettings, session: AsyncSession # Added session
) -> tuple[str, bool, list[str]]: # Return type changed from set to list for original_muted_users
    """
    Determines the mute action, updates MutedUser table, and returns original settings.
    """
    # Get current muted usernames from MutedUser table
    stmt_select = select(MutedUser.muted_teamtalk_username).where(MutedUser.user_settings_telegram_id == user_settings.telegram_id)
    result = await session.execute(stmt_select)
    current_muted_list = result.scalars().all()
    original_muted_usernames_list = list(current_muted_list) # Make a copy

    action_taken: str
    current_status_is_muted: bool # Is the user considered muted *before* this toggle action

    is_currently_in_db_list = username_to_toggle in current_muted_list

    if user_settings.mute_all:
        # Mute all ON: MutedUser table stores ALLOWED users (exceptions to mute all)
        if is_currently_in_db_list: # User was in allowed list
            # Remove from allowed list (means user becomes muted by Mute All)
            stmt_delete = delete(MutedUser).where(
                MutedUser.user_settings_telegram_id == user_settings.telegram_id,
                MutedUser.muted_teamtalk_username == username_to_toggle
            )
            await session.execute(stmt_delete)
            action_taken = "removed_from_allowed_list"
            current_status_is_muted = False # Was allowed, now effectively muted
        else: # User was not in allowed list (means user was muted by Mute All)
            # Add to allowed list
            new_entry = MutedUser(user_settings_telegram_id=user_settings.telegram_id, muted_teamtalk_username=username_to_toggle)
            session.add(new_entry)
            action_taken = "added_to_allowed_list"
            current_status_is_muted = True # Was effectively muted, now allowed
    else:
        # Mute all OFF: MutedUser table stores MUTED users
        if is_currently_in_db_list: # User was in muted list
            # Remove from muted list (means user becomes unmuted)
            stmt_delete = delete(MutedUser).where(
                MutedUser.user_settings_telegram_id == user_settings.telegram_id,
                MutedUser.muted_teamtalk_username == username_to_toggle
            )
            await session.execute(stmt_delete)
            action_taken = "removed_from_muted_list"
            current_status_is_muted = True # Was muted, now unmuted
        else: # User was not in muted list (means user was unmuted)
            # Add to muted list
            new_entry = MutedUser(user_settings_telegram_id=user_settings.telegram_id, muted_teamtalk_username=username_to_toggle)
            session.add(new_entry)
            action_taken = "added_to_muted_list"
            current_status_is_muted = False # Was unmuted, now muted

    # No need for set_muted_users_from_set, changes are made directly to DB via session
    # The session will be committed in _save_mute_settings_and_notify
    return action_taken, current_status_is_muted, original_muted_usernames_list


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
    user_settings: UserSettings, # UserSettings might be updated (e.g. mute_all)
    toast_message: str,
    username_to_toggle: str, # For logging
    action_taken: str, # For logging
    original_muted_usernames_list: list[str], # PARAMETER RENAMED and type changed
    _: callable
) -> bool:
    """
    Commits session (which includes MutedUser changes and potentially UserSettings changes),
    sends toast notification, and handles errors/reverts.
    Returns True if successful, False otherwise.
    """
    if not callback_query.from_user:
        logger.error("Cannot save settings: callback_query.from_user is None.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return False

    try:
        # UserSettings related to mute_all might have been changed by its own handler and added to session.
        # MutedUser changes (add/delete) are already in the session from _determine_mute_action_and_update_settings.
        # This commit will save both UserSettings changes (if any) and MutedUser changes.
        await session.commit()

        # Refresh user_settings from DB as its state (e.g. mute_all or related collections) might have changed.
        await session.refresh(user_settings)

        # Update cache as user_settings might have changed (e.g. mute_all status)
        # The muted_users_list relationship will also be updated by the refresh.
        from bot.core.user_settings import USER_SETTINGS_CACHE # Local import
        USER_SETTINGS_CACHE[user_settings.telegram_id] = user_settings

        await callback_query.answer(toast_message, show_alert=False)
        return True
    except Exception as e:
        logger.error(f"DB commit/Answer error for {username_to_toggle} (action: {action_taken}): {e}", exc_info=True)
        await session.rollback() # Rollback any changes in the session (MutedUser, UserSettings)
        # After rollback, user_settings object in memory might be stale.
        # The original_muted_usernames_list was for context; actual DB state is reverted by rollback.
        # If user_settings.mute_all was changed, that too is rolled back.
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return False


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: ToggleMuteSpecificCallback, # Contains list_type and current_page
    session: AsyncSession # Added session
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
        await _display_internal_user_list(callback_query, _, user_settings, list_type_user_was_on, current_page_for_refresh, session) # Added session


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
    callback_query: CallbackQuery, session: AsyncSession, _: callable, user_settings: UserSettings, callback_data: UserListCallback
): # Added session
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

    await _display_internal_user_list(callback_query, _, user_settings, effective_list_type, 0, session) # Added session


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery, session: AsyncSession, _: callable, user_settings: UserSettings, callback_data: PaginateUsersCallback
): # Added session
    await callback_query.answer()
    # callback_data.list_type is already UserListAction from CallbackData definition
    await _display_internal_user_list(callback_query, _, user_settings, callback_data.list_type, callback_data.page, session) # Added session


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
    # Pass session to _parse_mute_toggle_callback_data
    username_to_toggle = await _parse_mute_toggle_callback_data(callback_data, user_settings, session)

    if not username_to_toggle:
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    # Pass session to _determine_mute_action_and_update_settings
    # It now returns original_muted_usernames_list (list[str])
    action_taken, current_status_is_muted, original_muted_usernames_list = \
        await _determine_mute_action_and_update_settings(username_to_toggle, user_settings, session)

    # This logic remains the same: new_status_is_muted is the state *after* the toggle.
    # If current_status_is_muted was True (meaning user *was* muted before toggle),
    # then new_status_is_muted will be False (user is *now* unmuted).
    # If current_status_is_muted was False (user *was* unmuted before toggle),
    # then new_status_is_muted will be True (user is *now* muted).
    # This seems inverted compared to the previous logic. Let's re-evaluate.

    # Let's trace:
    # _determine_mute_action_and_update_settings returns `current_status_is_muted` which is the state *before* the toggle.
    # Example: mute_all=False (normal mode). User 'xyz' is NOT in MutedUser table.
    #   - is_currently_in_db_list = False
    #   - current_status_is_muted = False (was unmuted)
    #   - Action: add 'xyz' to MutedUser. User becomes muted.
    #   - We want toast "xyz is now muted". So new_status_is_muted should be True.
    #   - current_status_is_muted (False) != new_status_is_muted (True)

    # Example: mute_all=False. User 'xyz' IS in MutedUser table.
    #   - is_currently_in_db_list = True
    #   - current_status_is_muted = True (was muted)
    #   - Action: remove 'xyz' from MutedUser. User becomes unmuted.
    #   - We want toast "xyz is now unmuted". So new_status_is_muted should be False.
    #   - current_status_is_muted (True) != new_status_is_muted (False)

    # So, `new_status_is_muted` should indeed be the opposite of `current_status_is_muted` (the status *before* action).
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
        original_muted_usernames_list, # Pass the renamed variable
        _
    )

    if not save_successful:
        return

    await _refresh_mute_related_ui(
        callback_query,
        _,
        user_settings,
        tt_instance,
        callback_data,
        session # Pass session
    )
