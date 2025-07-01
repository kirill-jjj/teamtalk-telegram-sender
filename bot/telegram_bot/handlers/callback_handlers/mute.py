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
    MuteAllCallback,
    UserListCallback,
    PaginateUsersCallback,
    ToggleMuteSpecificCallback,
)
from bot.core.enums import (
    NotificationAction,
    MuteAllAction,
    UserListAction,
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
    if list_type == UserListAction.LIST_MUTED:
        header_text = _("Muted Users (Block List)")
        empty_list_text = _("You haven't muted anyone yet.")
    elif list_type == UserListAction.LIST_ALLOWED:
        header_text = _("Allowed Users (Allow List)")
        empty_list_text = _("No users are currently on the allow list.")
    else:
        logger.error(f"Unknown list_type '{list_type.value if isinstance(list_type, UserListAction) else list_type}' in _display_internal_user_list")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

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
    new_status_is_muted: bool

    if user_settings.mute_all:
        if is_currently_in_db_list:
            action_to_take = "remove"
            new_status_is_muted = True
        else:
            action_to_take = "add"
            new_status_is_muted = False
    else:
        if is_currently_in_db_list:
            action_to_take = "remove"
            new_status_is_muted = False
        else:
            action_to_take = "add"
            new_status_is_muted = True

    return action_to_take, new_status_is_muted


def _generate_mute_toggle_toast_message(
    username_to_toggle: str,
    new_status_is_muted: bool,
    mute_all_flag: bool,
    _: callable
) -> str:
    quoted_username = html.quote(username_to_toggle)
    status_text: str

    if new_status_is_muted:
        status_text = _("muted (due to Mute All mode)") if mute_all_flag else _("muted")
    else:
        status_text = _("allowed (in Mute All mode)") if mute_all_flag else _("unmuted")

    return _("{username} is now {status}.").format(username=quoted_username, status=status_text)


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
    callback_data: NotificationActionCallback, # This parameter was in the original user code, keep it for consistency
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
    callback_query: CallbackQuery, session: AsyncSession, _: callable, user_settings: UserSettings, callback_data: MuteAllCallback # This parameter was in the original user code
):
    managed_user_settings = await session.merge(user_settings)
    original_flag = managed_user_settings.mute_all

    def update_logic():
        managed_user_settings.mute_all = not original_flag

    def revert_logic():
        managed_user_settings.mute_all = original_flag

    new_status_display_text = _("Enabled") if not original_flag else _("Disabled")
    success_toast_text = _("Mute All mode is now {status}.").format(status=new_status_display_text)

    def refresh_ui_callable() -> tuple[str, InlineKeyboardMarkup]:
        # Create the keyboard with the LATEST user_settings state after potential update_logic
        # The process_setting_update will call this AFTER committing changes and refreshing user_settings
        updated_builder = create_manage_muted_users_keyboard(_, managed_user_settings) # Use managed_user_settings
        menu_text = _("Manage Muted/Allowed Users")
        return menu_text, updated_builder.as_markup()

    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=managed_user_settings,
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
    requested_list_type = callback_data.action
    is_mute_all_active = user_settings.mute_all

    effective_list_type = requested_list_type
    if is_mute_all_active:
        if requested_list_type == UserListAction.LIST_MUTED:
            effective_list_type = UserListAction.LIST_ALLOWED
    else:
        if requested_list_type == UserListAction.LIST_ALLOWED:
            effective_list_type = UserListAction.LIST_MUTED

    await _display_internal_user_list(callback_query, _, user_settings, effective_list_type, 0, session)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery, session: AsyncSession, _: callable, user_settings: UserSettings, callback_data: PaginateUsersCallback
):
    await callback_query.answer()
    # Note: The pagination callback carries the `list_type` that was used for the initial display.
    # This means `callback_data.list_type` here is the `effective_list_type` from `cq_list_internal_users_action`.
    await _display_internal_user_list(callback_query, _, user_settings, callback_data.list_type, callback_data.page, session)


@mute_router.callback_query(UserListCallback.filter(F.action == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_show_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_instance: Optional[TeamTalkInstance],
    callback_data: UserListCallback, # This parameter was in the original user code
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

    action_to_take, new_status_is_muted = _plan_mute_toggle_action(username_to_toggle, managed_user_settings)

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
        new_status_is_muted,
        managed_user_settings.mute_all,
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
