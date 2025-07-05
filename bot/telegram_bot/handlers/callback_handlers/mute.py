import logging
import math
from typing import Callable, Optional, Tuple
from aiogram import Router, F, html
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select, delete

import pytalk
from bot.teamtalk_bot.connection import TeamTalkConnection

from bot.models import UserSettings, MutedUser
from bot.telegram_bot.keyboards import (
    create_manage_muted_users_keyboard,
    create_paginated_user_list_keyboard,
    create_account_list_keyboard,
)
from bot.telegram_bot.callback_data import (
    NotificationActionCallback, # Used by cq_show_manage_muted_menu for nav
    SetMuteModeCallback,
    UserListCallback,
    PaginateUsersCallback,
    ToggleMuteSpecificCallback,
)
from bot.core.enums import (
    NotificationAction, # Used by cq_show_manage_muted_menu for nav
    UserListAction,
    ToggleMuteSpecificAction
)
from bot.models import MuteListMode
from bot.constants import USERS_PER_PAGE
from bot.telegram_bot.middlewares import TeamTalkConnectionCheckMiddleware
from ._helpers import process_setting_update, safe_edit_text

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)
mute_router = Router(name="callback_handlers.mute")
mute_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware()) # Apply to all CbQs in this router
ttstr = pytalk.instance.sdk.ttstr


def _paginate_list_util(full_list: list, page: int, page_size: int) -> tuple[list, int, int]:
    total_items = len(full_list)
    total_pages = int(math.ceil(total_items / page_size)) if total_items > 0 else 1
    page = max(0, min(page, total_pages - 1)) # Ensure page is within valid range
    start_index = page * page_size
    end_index = start_index + page_size
    page_slice = full_list[start_index:end_index]
    return page_slice, total_pages, page


async def _display_paginated_list_ui(
    callback_query: CallbackQuery,
    _: callable,
    items: list,
    page: int,
    header_text_key: str, # This is already translated text
    empty_list_text_key: str, # This is already translated text
    keyboard_factory: Callable[..., InlineKeyboardMarkup],
    keyboard_factory_kwargs: dict,
    server_host_for_display: Optional[str] = None # For context
) -> None:
    page_slice, total_pages, current_page_idx = _paginate_list_util(items, page, USERS_PER_PAGE)

    message_parts = [header_text_key] # Use pre-translated header
    if not items:
        message_parts.append(empty_list_text_key) # Use pre-translated empty text

    page_indicator_text = _("Page {current_page}/{total_pages}").format(
        current_page=current_page_idx + 1, total_pages=total_pages
    )
    if server_host_for_display:
         message_parts[0] += _(" on {server_host}").format(server_host=server_host_for_display)

    message_parts.append(f"\n{page_indicator_text}")
    final_message_text = "\n".join(message_parts)

    # Ensure callback_query.message is not None
    if not callback_query.message:
        logger.warning(f"Cannot display paginated list for '{header_text_key}', callback_query.message is None.")
        await callback_query.answer(_("Error displaying list."), show_alert=True)
        return

    keyboard_markup = await keyboard_factory(
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

    try:
        statement = select(MutedUser.muted_teamtalk_username).where(MutedUser.user_settings_telegram_id == user_settings.telegram_id)
        results = await session.execute(statement)
        # Ensure usernames are strings, not SQLModel rows or other objects if not already
        users_to_process = [str(username) for username in results.scalars().all()]
        sorted_items = sorted(users_to_process)
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching internal user list for user {user_settings.telegram_id}: {e}", exc_info=True)
        await callback_query.answer(_("An error occurred while loading the list. Please try again later."), show_alert=True)
        return

    header_text_str, empty_list_text_str = "", ""
    if user_settings.mute_list_mode == MuteListMode.blacklist:
        header_text_str = _("Blacklisted Users (Block List)")
        empty_list_text_str = _("Your blacklist is empty.")
    elif user_settings.mute_list_mode == MuteListMode.whitelist:
        header_text_str = _("Whitelisted Users (Allow List)")
        empty_list_text_str = _("Your whitelist is empty.")
    else:
        logger.error(f"Unknown mute_list_mode '{user_settings.mute_list_mode}' in _display_internal_user_list")
        await callback_query.answer(_("An error occurred due to an invalid mode. Please try again later."), show_alert=True)
        return

    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_,
        items=sorted_items,
        page=page,
        header_text_key=header_text_str, # Pass translated string
        empty_list_text_key=empty_list_text_str, # Pass translated string
        keyboard_factory=create_paginated_user_list_keyboard,
        keyboard_factory_kwargs={"list_type": list_type, "user_settings": user_settings},
    )


async def _display_all_server_accounts_list(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection,
    page: int = 0,
):
    if not callback_query.message:
        logger.warning("_display_all_server_accounts_list: callback_query.message is None.")
        await callback_query.answer(_("Error displaying accounts."), show_alert=True)
        return

    user_accounts_cache = tt_connection.user_accounts_cache
    server_host = tt_connection.server_info.host

    if not user_accounts_cache:
        try:
            await callback_query.message.edit_text(_("Server user accounts are not loaded yet for {server_host}. Please try again in a moment.").format(server_host=server_host))
        except TelegramAPIError as e:
            logger.error(f"Error informing user about empty user_accounts_cache for {server_host}: {e}")
        return

    all_accounts_tt = list(user_accounts_cache.values())
    sorted_items = sorted(all_accounts_tt, key=lambda acc: ttstr(acc.username).lower() if isinstance(acc.username, bytes) else str(acc.username).lower())


    await _display_paginated_list_ui(
        callback_query=callback_query,
        _=_,
        items=sorted_items,
        page=page,
        header_text_key=_("All Server Accounts"),
        empty_list_text_key=_("No user accounts found on the server."),
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={"user_settings": user_settings},
        server_host_for_display=server_host
    )


async def _get_username_to_toggle_from_callback(
    callback_data: ToggleMuteSpecificCallback,
    user_settings: UserSettings,
    session: AsyncSession,
    tt_connection: Optional[TeamTalkConnection]
) -> Optional[str]:
    user_idx = callback_data.user_idx
    current_page = callback_data.current_page
    list_type = callback_data.list_type

    if list_type == UserListAction.LIST_ALL_ACCOUNTS:
        if not tt_connection or not tt_connection.user_accounts_cache:
            logger.warning("Attempted to get username from 'all_accounts' list, but tt_connection or its user_accounts_cache is empty/None.")
            return None
        all_accounts = sorted(list(tt_connection.user_accounts_cache.values()), key=lambda acc: ttstr(acc.username).lower() if isinstance(acc.username, bytes) else str(acc.username).lower())
        page_items, _, _ = _paginate_list_util(all_accounts, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            username = page_items[user_idx].username
            return ttstr(username) if isinstance(username, bytes) else str(username)
    elif list_type in [UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]:
        statement = select(MutedUser.muted_teamtalk_username).where(MutedUser.user_settings_telegram_id == user_settings.telegram_id)
        results = await session.execute(statement)
        relevant_usernames = sorted([str(uname) for uname in results.scalars().all()])
        page_items, _, _ = _paginate_list_util(relevant_usernames, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            return page_items[user_idx]

    logger.warning(f"Could not find username for toggle. Idx: {user_idx}, List: {list_type.value if isinstance(list_type, UserListAction) else list_type}, Page: {current_page}")
    return None


def _plan_mute_toggle_action(username_to_toggle: str, user_settings: UserSettings) -> Tuple[str, bool]:
    current_muted_usernames = {mu.muted_teamtalk_username for mu in user_settings.muted_users_list}
    is_currently_in_db_list = username_to_toggle in current_muted_usernames
    action_to_take = "remove" if is_currently_in_db_list else "add"
    was_added_to_list = action_to_take == "add"
    return action_to_take, was_added_to_list


def _generate_mute_toggle_toast_message(
    username_to_toggle: str,
    was_added_to_list: bool,
    current_mode: MuteListMode,
    _: callable
) -> str:
    clean_username = username_to_toggle
    if clean_username.startswith("<") and clean_username.endswith(">"):
        clean_username = clean_username[1:-1]
    quoted_username = html.quote(clean_username)
    action_text = (_("added to blacklist") if was_added_to_list else _("removed from blacklist")) \
                  if current_mode == MuteListMode.blacklist \
                  else (_("added to whitelist") if was_added_to_list else _("removed from whitelist"))
    return _("{username} has been {action}.").format(username=quoted_username, action=action_text)


async def _commit_mute_changes_and_notify(
    session: AsyncSession,
    callback_query: CallbackQuery,
    user_settings: UserSettings,
    toast_message: str,
    app: "Application"
) -> bool:
    if not callback_query.from_user:
        logger.error("Cannot save settings: callback_query.from_user is None.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return False

    try:
        await session.commit()
        await session.refresh(user_settings)
        # SQLModel often handles relationship refreshing well,
        # but explicit refresh can be added if issues with muted_users_list persist.
        # await session.refresh(user_settings, attribute_names=['muted_users_list'])

        app.user_settings_cache[user_settings.telegram_id] = user_settings

        await callback_query.answer(toast_message, show_alert=False)
        return True
    except SQLAlchemyError as e:
        logger.error(f"DB commit/Answer error during mute toggle: {e}", exc_info=True)
        await session.rollback()
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return False


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: ToggleMuteSpecificCallback,
    session: AsyncSession
) -> None:
    list_type_user_was_on = callback_data.list_type
    current_page_for_refresh = callback_data.current_page

    if not callback_query.message:
        logger.warning("_refresh_mute_related_ui: callback_query.message is None. Cannot refresh UI.")
        await callback_query.answer(_("Error refreshing UI."), show_alert=True)
        return

    if list_type_user_was_on == UserListAction.LIST_ALL_ACCOUNTS:
        if tt_connection and tt_connection.instance and tt_connection.instance.connected and tt_connection.instance.logged_in:
            await _display_all_server_accounts_list(callback_query, _, user_settings, tt_connection, current_page_for_refresh)
        else:
            await callback_query.answer(_("TeamTalk bot is disconnected. UI could not be fully refreshed."), show_alert=True)
            manage_muted_cb_data = NotificationActionCallback(action=NotificationAction.MANAGE_MUTED) # type: ignore
            await cq_show_manage_muted_menu(callback_query, _, user_settings, manage_muted_cb_data)
    else:
        await _display_internal_user_list(callback_query, _, user_settings, list_type_user_was_on, current_page_for_refresh, session)


@mute_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.MANAGE_MUTED))
async def cq_show_manage_muted_menu(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    callback_data: NotificationActionCallback
):
    await callback_query.answer()
    manage_muted_builder = await create_manage_muted_users_keyboard(_, user_settings)

    current_mode_text = _("Current mode is Blacklist. You receive notifications from everyone except those on the list.") \
                        if user_settings.mute_list_mode == MuteListMode.blacklist \
                        else _("Current mode is Whitelist. You only receive notifications from users on the list.")
    full_text = f"{_('Manage Mute List')}\n\n{current_mode_text}"

    if not callback_query.message:
        logger.warning("cq_show_manage_muted_menu: callback_query.message is None.")
        return

    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=full_text,
        reply_markup=manage_muted_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_manage_muted_menu"
    )

@mute_router.callback_query(SetMuteModeCallback.filter())
async def cq_set_mute_mode_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    callback_data: SetMuteModeCallback,
    app: "Application"
):
    managed_user_settings = await session.merge(user_settings)
    new_mode = callback_data.mode

    if managed_user_settings.mute_list_mode == new_mode:
        await callback_query.answer()
        return

    original_mode = managed_user_settings.mute_list_mode
    def update_logic(): managed_user_settings.mute_list_mode = new_mode
    def revert_logic(): managed_user_settings.mute_list_mode = original_mode

    mode_text = _("Blacklist") if new_mode == MuteListMode.blacklist else _("Whitelist")
    success_toast_text = _("Mute list mode set to {mode}.").format(mode=mode_text)

    new_current_mode_desc = _("Current mode is Blacklist. You receive notifications from everyone except those on the list.") \
                            if new_mode == MuteListMode.blacklist \
                            else _("Current mode is Whitelist. You only receive notifications from users on the list.")
    menu_text = f"{_('Manage Mute List')}\n\n{new_current_mode_desc}"
    updated_builder = await create_manage_muted_users_keyboard(_, managed_user_settings)


    await process_setting_update(
        callback_query=callback_query,
        session=session,
        user_settings=managed_user_settings,
        _=_,
        update_action=update_logic,
        revert_action=revert_logic,
        success_toast_text=success_toast_text,
        new_text=menu_text,
        new_markup=updated_builder.as_markup(),
        app=app
    )


@mute_router.callback_query(UserListCallback.filter(F.action.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_list_internal_users_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    callback_data: UserListCallback
):
    await callback_query.answer()
    await _display_internal_user_list(callback_query, _, user_settings, callback_data.action, 0, session)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])))
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    callback_data: PaginateUsersCallback
):
    await callback_query.answer()
    await _display_internal_user_list(callback_query, _, user_settings, callback_data.list_type, callback_data.page, session)


@mute_router.callback_query(UserListCallback.filter(F.action == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_show_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None
):
    await callback_query.answer()
    if not tt_connection:
        await callback_query.answer(_("TeamTalk connection not available."), show_alert=True)
        return

    await _display_all_server_accounts_list(callback_query, _, user_settings, tt_connection, 0)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_paginate_all_accounts_list_action(
    callback_query: CallbackQuery,
    _: callable,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: PaginateUsersCallback,
):
    await callback_query.answer()
    if not tt_connection:
        await callback_query.answer(_("TeamTalk connection not available."), show_alert=True)
        return

    await _display_all_server_accounts_list(callback_query, _, user_settings, tt_connection, callback_data.page)


@mute_router.callback_query(ToggleMuteSpecificCallback.filter(F.action == ToggleMuteSpecificAction.TOGGLE_USER))
async def cq_toggle_specific_user_mute_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: ToggleMuteSpecificCallback,
    app: "Application"
):
    if not tt_connection:
         await callback_query.answer(_("TeamTalk connection error."), show_alert=True)
         return

    managed_user_settings = await session.merge(user_settings)
    username_to_toggle = await _get_username_to_toggle_from_callback(
        callback_data, managed_user_settings, session, tt_connection
    )

    if not username_to_toggle:
        await callback_query.answer(_("Could not identify user to toggle. Please try again."), show_alert=True)
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
        username_to_toggle, was_added_to_list, managed_user_settings.mute_list_mode, _
    )

    save_successful = await _commit_mute_changes_and_notify(
        session, callback_query, managed_user_settings, toast_message, app
    )

    if not save_successful:
        return

    await _refresh_mute_related_ui(
        callback_query, _, managed_user_settings, tt_connection, callback_data, session
    )
