import logging
import math
from typing import Callable, Any, Optional, Tuple
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete

import pytalk
from pytalk.instance import TeamTalkInstance

from bot.models import UserSettings, MutedUser
from bot.core.user_settings import USER_SETTINGS_CACHE
from bot.telegram_bot.keyboards import (
    create_manage_muted_users_keyboard,
    create_paginated_user_list_keyboard,
    create_account_list_keyboard,
)
from bot.telegram_bot.callback_data import (
    NotificationActionCallback,
    # MuteAllCallback, # Removed
    SetMuteModeCallback, # Added
    UserListCallback,
    PaginateUsersCallback,
    ToggleMuteSpecificCallback,
)
from bot.core.enums import (
    NotificationAction,
    # MuteAllAction, # Removed
    UserListAction,
    ToggleMuteSpecificAction
)
from bot.models import MuteListMode # Added
from bot.constants import USERS_PER_PAGE
from bot.state import USER_ACCOUNTS_CACHE
from ._helpers import process_setting_update, safe_edit_text

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

    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=final_message_text,
        reply_markup=keyboard_markup,
        parse_mode="HTML",
        logger_instance=logger,
        log_context=f"_display_paginated_list_ui for {header_text_key}"
    )


async def _display_internal_user_list(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    list_type: UserListAction,
    page: int = 0,
    session: Optional[AsyncSession] = None,
):
    if not session:
        logger.error("Session not provided to _display_internal_user_list")
        await callback_query.answer(_("An error occurred. Please try again."), show_alert=True)
        return

    statement = select(MutedUser.muted_teamtalk_username).where(MutedUser.user_settings_telegram_id == user_settings.telegram_id)
    results = await session.execute(statement)
    users_to_process = results.scalars().all()
    sorted_items = sorted(list(users_to_process))

    header_text, empty_list_text = "", ""
    # Determine header and empty text based on current mute_list_mode
    if user_settings.mute_list_mode == MuteListMode.BLACKLIST:
        header_text = _("Blacklisted Users (Block List)")
        empty_list_text = _("Your blacklist is empty.")
    elif user_settings.mute_list_mode == MuteListMode.WHITELIST:
        header_text = _("Whitelisted Users (Allow List)")
        empty_list_text = _("Your whitelist is empty.")
    else: # Should not happen
        logger.error(f"Unknown mute_list_mode '{user_settings.mute_list_mode}' in _display_internal_user_list")
        await callback_query.answer(_("An error occurred due to an invalid mode. Please try again later."), show_alert=True)
        return

    # The `list_type` parameter for `create_paginated_user_list_keyboard` might still need
    # to differentiate if `UserListAction.LIST_ALLOWED` is ever used.
    # For now, the problem description implies `UserListAction.LIST_MUTED` is always used by the "Manage List" button.
    # The keyboard itself uses `user_settings` to determine mute status of each user.

    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_,
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
    tt_instance: TeamTalkInstance,
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

    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_,
        items=sorted_items,
        page=page,
        header_text_key=_("All Server Accounts"),
        empty_list_text_key=_("No user accounts found on the server."),
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={"user_settings": user_settings},
    )


async def _get_username_to_toggle_from_callback(
    callback_data: ToggleMuteSpecificCallback, user_settings: UserSettings, session: AsyncSession
) -> Optional[str]:
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
        statement = select(MutedUser.muted_teamtalk_username).where(MutedUser.user_settings_telegram_id == user_settings.telegram_id)
        results = await session.execute(statement)
        relevant_usernames = sorted(list(results.scalars().all()))
        page_items, _, _ = _paginate_list_util(relevant_usernames, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            return page_items[user_idx]

    logger.warning(f"Could not find username for toggle. Idx: {user_idx}, List: {list_type.value if isinstance(list_type, UserListAction) else list_type}, Page: {current_page}")
    return None


def _plan_mute_toggle_action(username_to_toggle: str, user_settings: UserSettings) -> Tuple[str, bool]:
    current_muted_usernames = {mu.muted_teamtalk_username for mu in user_settings.muted_users_list}
    is_currently_in_db_list = username_to_toggle in current_muted_usernames

    action_to_take: str
    # new_status_is_muted: bool # This is now determined by the list mode + action, not directly planned here.
    # The function now just plans if we add or remove from the MutedUser table.
    # The "effective" mute status is determined at runtime by the mode + list content.

    if is_currently_in_db_list:
        action_to_take = "remove" # If in DB, the action is to remove it
        # new_status_is_muted will depend on mode:
        #   BLACKLIST: removing means effectively UNMUTED
        #   WHITELIST: removing means effectively MUTED
    else:
        action_to_take = "add" # If not in DB, the action is to add it
        # new_status_is_muted will depend on mode:
        #   BLACKLIST: adding means effectively MUTED
        #   WHITELIST: adding means effectively UNMUTED

    # We return the action ("add" or "remove") and whether the user *was added* to the list.
    # The `was_added` flag is True if action_to_take is "add".
    was_added_to_list = action_to_take == "add"
    return action_to_take, was_added_to_list


def _generate_mute_toggle_toast_message(
    username_to_toggle: str,
    was_added_to_list: bool, # Changed from new_status_is_muted
    current_mode: MuteListMode, # Changed from mute_all_flag
    _: callable
) -> str:
    quoted_username = html.quote(username_to_toggle)
    action_text: str

    if current_mode == MuteListMode.BLACKLIST:
        action_text = _("added to blacklist") if was_added_to_list else _("removed from blacklist")
    else: # WHITELIST
        action_text = _("added to whitelist") if was_added_to_list else _("removed from whitelist")

    return _("{username} has been {action}.").format(username=quoted_username, action=action_text)


async def _commit_mute_changes_and_notify(
    session: AsyncSession,
    callback_query: CallbackQuery,
    user_settings: UserSettings,
    toast_message: str,
    _: callable
) -> bool:
    if not callback_query.from_user:
        logger.error("Cannot save settings: callback_query.from_user is None.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return False

    try:
        await session.commit()
        await session.refresh(user_settings)
        await session.refresh(user_settings, attribute_names=['muted_users_list'])

        USER_SETTINGS_CACHE[user_settings.telegram_id] = user_settings

        await callback_query.answer(toast_message, show_alert=False)
        return True
    except Exception as e:
        logger.error(f"DB commit/Answer error during mute toggle: {e}", exc_info=True)
        await session.rollback()
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return False


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: ToggleMuteSpecificCallback,
    session: AsyncSession
) -> None:
    list_type_user_was_on = callback_data.list_type
    current_page_for_refresh = callback_data.current_page

    if list_type_user_was_on == UserListAction.LIST_ALL_ACCOUNTS:
        if tt_instance and tt_instance.connected and tt_instance.logged_in:
            await _display_all_server_accounts_list(callback_query, _, user_settings, tt_instance, current_page_for_refresh)
        else:
            await callback_query.answer(_("TeamTalk bot is disconnected. UI could not be refreshed."), show_alert=True)
            manage_muted_cb_data = NotificationActionCallback(action=NotificationAction.MANAGE_MUTED)
            await cq_show_manage_muted_menu(callback_query, _, user_settings, manage_muted_cb_data)
    else:
        await _display_internal_user_list(callback_query, _, user_settings, list_type_user_was_on, current_page_for_refresh, session)


@mute_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.MANAGE_MUTED))
async def cq_show_manage_muted_menu(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
):
    await callback_query.answer()
    manage_muted_builder = create_manage_muted_users_keyboard(_, user_settings)

    # Updated text for manage muted menu
    current_mode_text = _("Current mode is Blacklist. You receive notifications from everyone except those on the list.")
    if user_settings.mute_list_mode == MuteListMode.WHITELIST:
        current_mode_text = _("Current mode is Whitelist. You only receive notifications from users on the list.")

    full_text = f"{_('Manage Mute List')}\n\n{current_mode_text}" # Main title + description

    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=full_text, # Use new full_text
        reply_markup=manage_muted_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_manage_muted_menu"
    )

# Removed cq_toggle_mute_all_action
# New handler for setting mute mode:
@mute_router.callback_query(SetMuteModeCallback.filter())
async def cq_set_mute_mode_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    callback_data: SetMuteModeCallback
):
    managed_user_settings = await session.merge(user_settings)
    new_mode = callback_data.mode

    if managed_user_settings.mute_list_mode == new_mode:
        await callback_query.answer() # Mode is already set, do nothing
        return

    original_mode = managed_user_settings.mute_list_mode

    def update_logic():
        managed_user_settings.mute_list_mode = new_mode

    def revert_logic():
        managed_user_settings.mute_list_mode = original_mode

    mode_text = _("Blacklist") if new_mode == MuteListMode.BLACKLIST else _("Whitelist")
    success_toast_text = _("Mute list mode set to {mode}.").format(mode=mode_text)

    def refresh_ui_callable() -> tuple[str, InlineKeyboardMarkup]:
        # After committing changes and refreshing user_settings, create the keyboard
        updated_builder = create_manage_muted_users_keyboard(_, managed_user_settings)

        # Generate the descriptive text for the menu again
        current_mode_desc = _("Current mode is Blacklist. You receive notifications from everyone except those on the list.")
        if managed_user_settings.mute_list_mode == MuteListMode.WHITELIST:
            current_mode_desc = _("Current mode is Whitelist. You only receive notifications from users on the list.")
        menu_text = f"{_('Manage Mute List')}\n\n{current_mode_desc}"

        return menu_text, updated_builder.as_markup()

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=managed_user_settings, # Pass the merged (managed) instance
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        ui_refresh_callable=refresh_ui_callable,
    )


@mute_router.callback_query(UserListCallback.filter(F.action.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_list_internal_users_action(
    callback_query: CallbackQuery, session: AsyncSession, _: callable, user_settings: UserSettings, callback_data: UserListCallback
):
    await callback_query.answer()
    # The requested_list_type from UserListCallback might become redundant if the UI always shows
    # the correct list based on current mode.
    # For now, we assume UserListAction.LIST_MUTED is always sent by the "Manage Blacklist/Whitelist" button.
    # The header text inside _display_internal_user_list will adapt.

    # The problem description's keyboard change:
    # list_mode_text = _("Manage Blacklist") if user_settings.mute_list_mode == MuteListMode.BLACKLIST else _("Manage Whitelist")
    # builder.button(
    #     text=list_mode_text,
    #     callback_data=UserListCallback(action=UserListAction.LIST_MUTED).pack() # Always LIST_MUTED
    # )
    # This implies that `callback_data.action` will be LIST_MUTED.
    # The actual display (header, etc.) should adapt based on `user_settings.mute_list_mode`.

    # We can simplify: the list_type for display is just what was passed,
    # and _display_internal_user_list should correctly interpret it or be adapted.
    # The old logic for `effective_list_type` is no longer needed because `mute_all` is gone.
    # The `_display_internal_user_list` function needs to correctly determine header/empty text based on `user_settings.mute_list_mode`.
    # It also needs to be adapted to show the correct header based on the current mute_list_mode.
    # Let's assume for now that UserListAction.LIST_MUTED implies "show the list of users who are exceptions"
    # (i.e., the blacklist if mode is blacklist, or the whitelist if mode is whitelist).

    await _display_internal_user_list(callback_query, _, user_settings, callback_data.action, 0, session)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery, session: AsyncSession, _: callable, user_settings: UserSettings, callback_data: PaginateUsersCallback
):
    await callback_query.answer()
    # Similar to above, _display_internal_user_list needs to handle the list_type correctly in context of mute_list_mode
    await _display_internal_user_list(callback_query, _, user_settings, callback_data.list_type, callback_data.page, session)


@mute_router.callback_query(UserListCallback.filter(F.action == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_show_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_instance: Optional[TeamTalkInstance],
):
    await callback_query.answer()
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await callback_query.message.edit_text(_("TeamTalk bot is not connected. Cannot display user list."))
        return
    if not USER_ACCOUNTS_CACHE:
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
    managed_user_settings = await session.merge(user_settings)

    username_to_toggle = await _get_username_to_toggle_from_callback(callback_data, managed_user_settings, session)

    if not username_to_toggle:
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    action_to_take, was_added_to_list = _plan_mute_toggle_action(username_to_toggle, managed_user_settings)

    if action_to_take == "add":
        new_entry = MutedUser(user_settings_telegram_id=managed_user_settings.telegram_id, muted_teamtalk_username=username_to_toggle)
        session.add(new_entry)
    elif action_to_take == "remove":
        stmt_delete = delete(MutedUser).where(
            MutedUser.user_settings_telegram_id == managed_user_settings.telegram_id,
            MutedUser.muted_teamtalk_username == username_to_toggle
        )
        await session.execute(stmt_delete)

    toast_message = _generate_mute_toggle_toast_message(
        username_to_toggle,
        was_added_to_list, # Use this instead of new_status_is_muted
        managed_user_settings.mute_list_mode, # Use current mode instead of mute_all
        _
    )

    save_successful = await _commit_mute_changes_and_notify(
        session,
        callback_query,
        managed_user_settings,
        toast_message,
        _
    )

    if not save_successful:
        return

    await _refresh_mute_related_ui(
        callback_query,
        _,
        managed_user_settings,
        tt_instance,
        callback_data,
        session
    )
