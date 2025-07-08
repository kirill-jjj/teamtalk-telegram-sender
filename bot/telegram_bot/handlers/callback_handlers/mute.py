"""Callback query handlers for mute list management and user muting/unmuting."""

from collections.abc import Callable
import gettext
import logging
from typing import TYPE_CHECKING

from aiogram import F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
import pytalk
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from bot.constants import USERS_PER_PAGE
from bot.core.enums import (
    NotificationAction,
    ToggleMuteSpecificAction,
    UserListAction,
)
from bot.models import MutedUser, MuteListMode, UserSettings
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    NotificationActionCallback,
    PaginateUsersCallback,
    SetMuteModeCallback,
    ToggleMuteSpecificCallback,
    UserListCallback,
)
from bot.telegram_bot.keyboards import (
    create_account_list_keyboard,
    create_manage_muted_users_keyboard,
    create_paginated_user_list_keyboard,
)
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware
from bot.services import user_service # Added missing import

from ._helpers import safe_edit_text

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
mute_router = Router(name="callback_handlers.mute")
mute_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
mute_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())
ttstr = pytalk.instance.sdk.ttstr


def _paginate_list_util(full_list: list, page: int, page_size: int) -> tuple[list, int, int]:
    total_items = len(full_list)
    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    page = max(0, min(page, total_pages - 1))
    start_index = page * page_size
    end_index = start_index + page_size
    page_slice = full_list[start_index:end_index]
    return page_slice, total_pages, page


async def _display_paginated_list_ui(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    items: list,
    page: int,
    header_text_key: str,
    empty_list_text_key: str,
    keyboard_factory: Callable[..., InlineKeyboardMarkup],
    keyboard_factory_kwargs: dict,
    server_host_for_display: str | None = None,
) -> None:
    _ = translator.gettext
    page_slice, total_pages, current_page_idx = _paginate_list_util(items, page, USERS_PER_PAGE)
    message_parts = [header_text_key]
    if not items:
        message_parts.append(empty_list_text_key)
    page_indicator_text = _("Page {current_page}/{total_pages}").format(
        current_page=current_page_idx + 1, total_pages=total_pages
    )
    if server_host_for_display:
        message_parts[0] += _(" on {server_host}").format(server_host=server_host_for_display)
    message_parts.append(f"\n{page_indicator_text}")
    final_message_text = "\n".join(message_parts)

    if not callback_query.message:
        logger.warning("Cannot display paginated list for '%s', callback_query.message is None.", header_text_key)
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    keyboard_markup = await keyboard_factory(
        translator, # Pass full translator object
        page_items=page_slice,
        current_page=current_page_idx,
        total_pages=total_pages,
        **keyboard_factory_kwargs
    )
    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=final_message_text,
        reply_markup=keyboard_markup,
        parse_mode="HTML",
        logger_instance=logger,
        log_context=f"_display_paginated_list_ui for {header_text_key}",
    )


async def _display_internal_user_list(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    list_type: UserListAction,
    page: int = 0,
    session: AsyncSession | None = None,
):
    _ = translator.gettext
    if not session:
        logger.error("Session not provided to _display_internal_user_list")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return
    try:
        statement = select(MutedUser.muted_teamtalk_username).where(
            MutedUser.user_settings_telegram_id == user_settings.telegram_id
        )
        results = await session.exec(statement)
        users_to_process = [str(username) for username in results.all()]
        sorted_items = sorted(users_to_process)
    except SQLAlchemyError as e:
        logger.exception("DB error fetching internal user list for user %s: %s", user_settings.telegram_id, e)
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    header_text_str, empty_list_text_str = "", ""
    if user_settings.mute_list_mode == MuteListMode.blacklist:
        header_text_str = _("Blacklisted Users (Block List)")
        empty_list_text_str = _("Your blacklist is empty.")
    elif user_settings.mute_list_mode == MuteListMode.whitelist:
        header_text_str = _("Whitelisted Users (Allow List)")
        empty_list_text_str = _("Your whitelist is empty.")
    else:
        logger.error("Unknown mute_list_mode '%s'", user_settings.mute_list_mode)
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    await _display_paginated_list_ui(
        callback_query=callback_query,
        translator=translator, # Pass full translator
        items=sorted_items,
        page=page,
        header_text_key=header_text_str,
        empty_list_text_key=empty_list_text_str,
        keyboard_factory=create_paginated_user_list_keyboard,
        keyboard_factory_kwargs={"list_type": list_type, "user_settings": user_settings},
    )


async def _display_all_server_accounts_list(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection,
    page: int = 0,
):
    _ = translator.gettext
    if not callback_query.message:
        logger.warning("_display_all_server_accounts_list: message is None.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    user_accounts_cache = tt_connection.user_accounts_cache
    server_host = tt_connection.server_info.host
    if not user_accounts_cache:
        try:
            await callback_query.message.edit_text(
                _("Server user accounts are not loaded yet for {server_host}. Please try again in a moment.").format(
                    server_host=server_host
                )
            )
        except TelegramAPIError as e:
            logger.error("Error informing user about empty accounts_cache for %s: %s", server_host, e)
        return

    all_accounts_tt = list(user_accounts_cache.values())
    sorted_items = sorted(
        all_accounts_tt,
        key=lambda acc: (ttstr(acc.username).lower() if isinstance(acc.username, bytes) else str(acc.username).lower()),
    )
    await _display_paginated_list_ui(
        callback_query=callback_query,
        translator=translator, # Pass full translator
        items=sorted_items,
        page=page,
        header_text_key=_("All Server Accounts"),
        empty_list_text_key=_("No user accounts found on the server."),
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={"user_settings": user_settings},
        server_host_for_display=server_host,
    )


async def _get_username_to_toggle_from_callback(
    callback_data: ToggleMuteSpecificCallback,
    user_settings: UserSettings,
    session: AsyncSession,
    tt_connection: TeamTalkConnection | None,
) -> str | None:
    user_idx = callback_data.user_idx
    current_page = callback_data.current_page
    list_type = callback_data.list_type
    if list_type == UserListAction.LIST_ALL_ACCOUNTS:
        if not tt_connection or not tt_connection.user_accounts_cache:
            logger.warning("Cannot get username from 'all_accounts': cache empty/None.")
            return None
        all_accounts = sorted(
            tt_connection.user_accounts_cache.values(),
            key=lambda acc: (
                ttstr(acc.username).lower() if isinstance(acc.username, bytes) else str(acc.username).lower()
            ),
        )
        page_items, _, _ = _paginate_list_util(all_accounts, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            username = page_items[user_idx].username
            return ttstr(username) if isinstance(username, bytes) else str(username)
    elif list_type in [UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]:
        statement = select(MutedUser.muted_teamtalk_username).where(
            MutedUser.user_settings_telegram_id == user_settings.telegram_id
        )
        results = await session.exec(statement)
        relevant_usernames = sorted([str(uname) for uname in results.all()])
        page_items, _, _ = _paginate_list_util(relevant_usernames, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            return page_items[user_idx]
    logger.warning("Could not find username for toggle. Idx: %s, List: %s, Page: %s",
                   user_idx, list_type.value if isinstance(list_type, UserListAction) else list_type, current_page)
    return None


# _plan_mute_toggle_action is removed, logic moved to user_service.toggle_mute_status_for_tt_user


def _generate_mute_toggle_toast_message(
    username_to_toggle: str, was_added_to_list: bool, current_mode: MuteListMode, translator: gettext.GNUTranslations
) -> str:
    _ = translator.gettext
    clean_username = username_to_toggle.strip("<>")
    quoted_username = html.quote(clean_username)
    action_key_map = {
        (MuteListMode.blacklist, True): "added to blacklist",
        (MuteListMode.blacklist, False): "removed from blacklist",
        (MuteListMode.whitelist, True): "added to whitelist",
        (MuteListMode.whitelist, False): "removed from whitelist",
    }
    action_text = _(action_key_map[(current_mode, was_added_to_list)])
    return _("{username} has been {action}.").format(username=quoted_username, action=action_text)


# _commit_mute_changes_and_notify is removed, logic moved to user_service.toggle_mute_status_for_tt_user
# and handler cq_toggle_specific_user_mute_action


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: ToggleMuteSpecificCallback,
    session: AsyncSession,
) -> None:
    """Refreshes the mute list UI after an action."""
    _ = translator.gettext
    list_type_user_was_on = callback_data.list_type
    current_page_for_refresh = callback_data.current_page

    if not callback_query.message:
        logger.warning("_refresh_mute_related_ui: callback_query.message is None. Cannot refresh UI.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return
    try:
        await session.refresh(user_settings, attribute_names=["muted_users_list"])
        logger.debug("Refreshed muted_users_list for user %s before UI refresh.", user_settings.telegram_id)
    except Exception as e:
        logger.exception("Failed to refresh user_settings relations for %s: %s", user_settings.telegram_id, e)
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    if list_type_user_was_on == UserListAction.LIST_ALL_ACCOUNTS:
        if tt_connection and tt_connection.is_ready:
            await _display_all_server_accounts_list(
                callback_query,
                translator,
                user_settings,
                tt_connection,
                current_page_for_refresh
            )
        else:
            await callback_query.answer(
                _("TeamTalk bot is disconnected. UI could not be fully refreshed."), show_alert=True
            )
            manage_muted_cb_data = NotificationActionCallback(action=NotificationAction.MANAGE_MUTED)
            await cq_show_manage_muted_menu(
                callback_query,
                translator,
                user_settings,
                manage_muted_cb_data
            )
    else:
        await _display_internal_user_list(
            callback_query,
            translator,
            user_settings,
            list_type_user_was_on,
            current_page_for_refresh,
            session
        )


@mute_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.MANAGE_MUTED))
async def cq_show_manage_muted_menu(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: NotificationActionCallback
):
    """Shows the main menu for managing muted users and mute list mode."""
    _ = translator.gettext
    await callback_query.answer()
    manage_muted_builder = await create_manage_muted_users_keyboard(
        translator, user_settings
    )
    if user_settings.mute_list_mode == MuteListMode.blacklist:
        current_mode_text = _(
            "Current mode is Blacklist. You receive notifications from everyone except those on the list."
        )
    else:
        current_mode_text = _("Current mode is Whitelist. You only receive notifications from users on the list.")
    full_text = _("Manage Mute List\n\n{current_mode_description}").format(
        current_mode_description=current_mode_text
    )
    if not callback_query.message:
        logger.warning("cq_show_manage_muted_menu: callback_query.message is None.")
        return
    await safe_edit_text(
        message_to_edit=callback_query.message,
        text=full_text,
        reply_markup=manage_muted_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_manage_muted_menu",
    )


@mute_router.callback_query(SetMuteModeCallback.filter())
async def cq_set_mute_mode_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: SetMuteModeCallback,
    services: "Services",
):
    """Handles the action of setting the mute list mode (blacklist/whitelist)."""
    _ = translator.gettext
    if not callback_query.message:
        logger.warning("cq_set_mute_mode_action: Callback query is missing message.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    managed_user_settings = await session.merge(user_settings)
    new_mode = callback_data.mode
    if managed_user_settings.mute_list_mode == new_mode:
        await callback_query.answer()
        return

    original_mode = managed_user_settings.mute_list_mode
    managed_user_settings.mute_list_mode = new_mode
    mode_text = _("Blacklist") if new_mode == MuteListMode.blacklist else _("Whitelist")
    if new_mode == MuteListMode.blacklist:
        new_current_mode_desc = _(
            "Current mode is Blacklist. You receive notifications from everyone except those on the list."
        )
    else:
        new_current_mode_desc = _("Current mode is Whitelist. You only receive notifications from users on the list.")
    menu_text = _("Manage Mute List\n\n{current_mode_description}").format(
        current_mode_description=new_current_mode_desc
    )
    updated_keyboard = await create_manage_muted_users_keyboard(translator, managed_user_settings)
    try:
        await session.commit()
        await session.refresh(managed_user_settings)
        services.cache.update_user_settings(managed_user_settings)
        success_toast_text = _("Mute list mode set to {mode}.").format(mode=mode_text)
        await callback_query.answer(success_toast_text)
        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=menu_text,
            reply_markup=updated_keyboard.as_markup(),
            logger_instance=logger,
            log_context="cq_set_mute_mode_action",
        )
    except SQLAlchemyError as e:
        managed_user_settings.mute_list_mode = original_mode
        await session.merge(managed_user_settings)
        await session.rollback()
        logger.exception("Failed to update mute list mode for user %s. Error: %s", callback_query.from_user.id, e)
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)


@mute_router.callback_query(
    UserListCallback.filter(F.action.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]))
)
async def cq_list_internal_users_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: UserListCallback,
):
    """Displays the first page of the internal muted/allowed user list."""
    _ = translator.gettext
    await callback_query.answer()
    await _display_internal_user_list(
        callback_query, translator, user_settings, callback_data.action, 0, session
    )


@mute_router.callback_query(
    PaginateUsersCallback.filter(F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]))
)
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: PaginateUsersCallback,
):
    """Handles pagination for the internal muted/allowed user list."""
    _ = translator.gettext
    await callback_query.answer()
    await _display_internal_user_list(
        callback_query, translator, user_settings,
        callback_data.list_type, callback_data.page, session
    )


@mute_router.callback_query(UserListCallback.filter(F.action == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_show_all_accounts_list_action(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None
):
    """Displays the first page of all TeamTalk server accounts for muting/unmuting."""
    _ = translator.gettext
    await callback_query.answer()
    if not tt_connection:
        await callback_query.answer(_("TeamTalk connection is not available. Please try again later."), show_alert=True)
        return
    await _display_all_server_accounts_list(
        callback_query, translator, user_settings, tt_connection, 0
    )


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_paginate_all_accounts_list_action(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: PaginateUsersCallback,
):
    """Handles pagination for the list of all TeamTalk server accounts."""
    _ = translator.gettext
    await callback_query.answer()
    if not tt_connection:
        await callback_query.answer(_("TeamTalk connection is not available. Please try again later."), show_alert=True)
        return
    await _display_all_server_accounts_list(
        callback_query, translator, user_settings, tt_connection, callback_data.page
    )


@mute_router.callback_query(ToggleMuteSpecificCallback.filter(F.action == ToggleMuteSpecificAction.TOGGLE_USER))
async def cq_toggle_specific_user_mute_action(
    callback_query: CallbackQuery,
    session: AsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: ToggleMuteSpecificCallback,
    services: "Services",
):
    """Handles the action of toggling the mute status for a specific user."""
    _ = translator.gettext
    if not tt_connection: # Should be caught by middleware, but good check
        # tt_connection might not be strictly needed if _get_username_to_toggle_from_callback can work without it
        # for list_type != LIST_ALL_ACCOUNTS. However, _refresh_mute_related_ui might need it.
        # For now, keeping the check.
        await callback_query.answer(_("TeamTalk connection is not available. Please try again later."), show_alert=True)
        return

    # user_settings is already managed by middleware, no need to merge unless making changes before service call
    # which we are not.
    username_to_toggle = await _get_username_to_toggle_from_callback(
        callback_data, user_settings, session, tt_connection
    )
    if not username_to_toggle:
        logger.warning(
            "Could not determine username to toggle mute for user %s. Callback data: %s",
            callback_query.from_user.id, callback_data
        )
        await callback_query.answer(_("An error occurred determining the user to mute/unmute. Please try again."), show_alert=True)
        return

    # --- Call the service function to handle all logic ---
    # N.B. user_settings object will be modified by the service if successful (due to session.refresh)
    # or if it directly manipulates the list and it's part of the same session.
    # The UserSettingsMiddleware should provide a session-attached object.
    was_successful, resulting_action = await user_service.toggle_mute_status_for_tt_user(
        session, user_settings, username_to_toggle, services
    )
    # ----------------------------------------------------

    if not was_successful:
        await callback_query.answer(_("An error occurred while updating mute status. Please try again later."), show_alert=True)
        return

    # Generate toast message based on the action performed by the service
    if resulting_action == "muted":
        toast_message = _generate_mute_toggle_toast_message(
            username_to_toggle, True, user_settings.mute_list_mode, translator
        )
    elif resulting_action == "unmuted":
        toast_message = _generate_mute_toggle_toast_message(
            username_to_toggle, False, user_settings.mute_list_mode, translator
        )
    else: # Should not happen if was_successful is True
        logger.error("toggle_mute_status_for_tt_user reported success but no valid resulting_action.")
        toast_message = _("Mute status updated.")


    await callback_query.answer(toast_message, show_alert=False)

    # UI refresh still needs the potentially updated user_settings from the service call
    await _refresh_mute_related_ui(
        callback_query, translator, user_settings, tt_connection, callback_data, session
    )
