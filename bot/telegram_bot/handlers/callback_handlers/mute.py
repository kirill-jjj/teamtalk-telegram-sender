"""Callback query handlers for mute list management and user muting/unmuting."""

import gettext
import logging
from typing import (  # Added Any, TypeVar
    TYPE_CHECKING,
    TypeVar,
    cast,  # Separate import for cast
)

from aiogram import F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message  # Added Message
import pytalk
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession  # Keep if other functions use it
from sqlmodel import select

# Import SQLModel's AsyncSession and alias the other one if needed, or just use one consistently.
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from bot.constants import USERS_PER_PAGE
from bot.core.enums import (
    NotificationAction,
    ToggleMuteSpecificAction,
    UserListAction,
)
from bot.models import MutedUser, MuteListMode, UserSettings
from bot.services import user_service
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
from bot.telegram_bot.ui_utils import display_paginated_list, paginate_list  # Ensured both are imported

from ._helpers import safe_edit_text

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
mute_router = Router(name="callback_handlers.mute")
mute_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
mute_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())
ttstr = pytalk.instance.sdk.ttstr

T = TypeVar("T")


# _paginate_list_util MOVED to ui_utils.py and renamed to paginate_list


# _display_paginated_list_ui MOVED to ui_utils.py and renamed to display_paginated_list


async def _display_internal_user_list(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    list_type: UserListAction,
    page: int = 0,
    session: SQLModelAsyncSession | None = None,  # Expect SQLModel session
) -> None:
    _ = translator.gettext
    if not session:
        logger.error("Session not provided to _display_internal_user_list")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return
    try:
        statement = select(MutedUser.muted_teamtalk_username).where(
            MutedUser.user_settings_telegram_id == user_settings.telegram_id
        )
        results = await session.exec(statement)  # Now compatible
        users_to_process = [str(username) for username in results.all()]
        sorted_items = sorted(users_to_process)
    except SQLAlchemyError:
        logger.exception("DB error fetching internal user list for user %s.", user_settings.telegram_id)
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

    await display_paginated_list(
        target=callback_query,  # Changed to target
        bot=callback_query.bot,  # Added bot instance
        translator=translator,
        items=sorted_items,
        page=page,
        title_text=header_text_str,
        empty_list_text=empty_list_text_str,
        keyboard_factory=create_paginated_user_list_keyboard,
        keyboard_factory_kwargs={"list_type": list_type, "user_settings": user_settings},
    )


async def _display_all_server_accounts_list(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection,
    page: int = 0,
) -> None:
    _ = translator.gettext
    if not isinstance(callback_query.message, Message):
        logger.warning(
            "_display_all_server_accounts_list: Message is None or inaccessible for user %s.",
            callback_query.from_user.id if callback_query.from_user else "Unknown",
        )
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    user_accounts_cache = tt_connection.user_accounts_cache
    server_host = tt_connection.server_info.host
    message_obj: Message = callback_query.message  # Assign to new variable after check

    if not user_accounts_cache:
        try:
            await message_obj.edit_text(
                _("Server user accounts are not loaded yet for {server_host}. Please try again in a moment.").format(
                    server_host=server_host
                )
            )
        except TelegramAPIError:
            logger.exception("Error informing user about empty accounts_cache for %s.", server_host)
        return

    all_accounts_tt = list(user_accounts_cache.values())
    sorted_items = sorted(
        all_accounts_tt,
        key=lambda acc: (ttstr(acc.username).lower() if isinstance(acc.username, bytes) else str(acc.username).lower()),
    )
    await display_paginated_list(
        target=callback_query,  # Changed to target
        bot=callback_query.bot,  # Added bot instance
        translator=translator,
        items=sorted_items,
        page=page,
        title_text=_("All Server Accounts"),  # Renamed parameter
        empty_list_text=_("No user accounts found on the server."),  # Renamed parameter
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={"user_settings": user_settings},
        server_host_for_display=server_host,
    )


async def _get_username_to_toggle_from_callback(
    callback_data: ToggleMuteSpecificCallback,
    user_settings: UserSettings,
    session: SQLAlchemyAsyncSession,
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
        page_items, _, _ = paginate_list(all_accounts, current_page, USERS_PER_PAGE)  # Use renamed paginate_list
        if 0 <= user_idx < len(page_items):
            username_attr = page_items[user_idx].username
            # Assuming ttstr handles bytes and returns str. If username_attr can be None, handle it.
            return cast(str, ttstr(username_attr)) if username_attr is not None else None
    elif list_type in [UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]:
        statement = select(MutedUser.muted_teamtalk_username).where(
            MutedUser.user_settings_telegram_id == user_settings.telegram_id
        )
        results = await session.execute(statement)
        relevant_usernames = sorted([str(uname) for uname in results.scalars().all()])  # Use .scalars()
        page_items, _, _ = paginate_list(relevant_usernames, current_page, USERS_PER_PAGE)  # Use renamed paginate_list
        if 0 <= user_idx < len(page_items):
            return page_items[user_idx]  # type: ignore[no-any-return]
    logger.warning(
        "Could not find username for toggle. Idx: %s, List: %s, Page: %s",
        user_idx,
        list_type.value if isinstance(list_type, UserListAction) else list_type,
        current_page,
    )
    return None


# _plan_mute_toggle_action is removed, logic moved to user_service.toggle_mute_status_for_tt_user


def _generate_mute_toggle_toast_message(
    username_to_toggle: str, *, was_added_to_list: bool, current_mode: MuteListMode, translator: gettext.GNUTranslations
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
    session: SQLAlchemyAsyncSession,  # Parameter is SQLAlchemy's session
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
    except Exception:
        logger.exception("Failed to refresh user_settings relations for %s.", user_settings.telegram_id)
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    if list_type_user_was_on == UserListAction.LIST_ALL_ACCOUNTS:
        if tt_connection and tt_connection.is_ready:
            await _display_all_server_accounts_list(
                callback_query, translator, user_settings, tt_connection, current_page_for_refresh
            )
        else:
            await callback_query.answer(
                _("TeamTalk bot is disconnected. UI could not be fully refreshed."), show_alert=True
            )
            manage_muted_cb_data = NotificationActionCallback(action=NotificationAction.MANAGE_MUTED)
            await cq_show_manage_muted_menu(callback_query, translator, user_settings, manage_muted_cb_data)
    else:
        await _display_internal_user_list(
            callback_query,
            translator,
            user_settings,
            list_type_user_was_on,
            current_page_for_refresh,
            cast(SQLModelAsyncSession, session),
        )


@mute_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.MANAGE_MUTED))
async def cq_show_manage_muted_menu(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    _callback_data: NotificationActionCallback | None = None,  # Keep for consistent signature, though not used
) -> None:
    """Shows the main menu for managing muted users and mute list mode."""
    _ = translator.gettext
    await callback_query.answer()
    manage_muted_builder = await create_manage_muted_users_keyboard(translator, user_settings)
    if user_settings.mute_list_mode == MuteListMode.blacklist:
        current_mode_text = _(
            "Current mode is Blacklist. You receive notifications from everyone except those on the list."
        )
    else:
        current_mode_text = _("Current mode is Whitelist. You only receive notifications from users on the list.")
    full_text = _("Manage Mute List\n\n{current_mode_description}").format(current_mode_description=current_mode_text)

    if not isinstance(callback_query.message, Message):
        logger.warning(
            "cq_show_manage_muted_menu: Message is None or inaccessible for user %s. Callback data: %s",
            callback_query.from_user.id if callback_query.from_user else "Unknown",
            _callback_data.pack() if _callback_data else callback_query.data,
        )
        # Attempt to answer the callback even if we can't edit the message
        try:
            await callback_query.answer(
                _("Could not update the message view. Please try navigating again."), show_alert=True
            )
        except TelegramAPIError:
            logger.exception("Failed to answer callback in cq_show_manage_muted_menu for inaccessible message.")
        return

    await safe_edit_text(
        message_to_edit=callback_query.message,  # Now known to be Message
        text=full_text,
        reply_markup=manage_muted_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_manage_muted_menu",
    )


@mute_router.callback_query(SetMuteModeCallback.filter())
async def cq_set_mute_mode_action(
    callback_query: CallbackQuery,
    session: SQLAlchemyAsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: SetMuteModeCallback,
    services: "Services",
) -> None:
    """Handles the action of setting the mute list mode (blacklist/whitelist)."""
    _ = translator.gettext
    if not callback_query.message:
        logger.warning("cq_set_mute_mode_action: Callback query is missing message.")
        await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        return

    new_mode = callback_data.mode

    # The user_settings object from middleware should already be session-managed.
    # The service function `set_user_mute_mode` will handle merging if necessary,
    # committing, cache updates, and error handling.
    updated_user_settings = await user_service.set_user_mute_mode(session, services, user_settings, new_mode)

    if not updated_user_settings:
        # Service function handles logging and rollback.
        # Inform user of failure. The user_settings object might be in its original state
        # or state before the failed commit attempt if service function restored it.
        await callback_query.answer(
            _("An error occurred while updating mute mode. Please try again later."), show_alert=True
        )
        # We might need to refresh the UI to reflect the (potentially) unchanged state.
        # For now, just answering. If the settings object was mutated then rolled back,
        # the keyboard might be built with this transient state if not careful.
        # However, create_manage_muted_users_keyboard should use the state from the object as it is.
        # Let's ensure we pass the original user_settings if update failed, or the updated one if success.
        # The `user_settings` variable itself might have been modified by `set_user_mute_mode` if it did a rollback
        # and restored the original value to the passed object.
        # For simplicity, we'll rely on the service to have restored the object's state on failure.
        current_settings_for_keyboard = user_settings
    else:
        # Success
        mode_text = _("Blacklist") if updated_user_settings.mute_list_mode == MuteListMode.blacklist else _("Whitelist")
        success_toast_text = _("Mute list mode set to {mode}.").format(mode=mode_text)
        await callback_query.answer(success_toast_text)
        current_settings_for_keyboard = updated_user_settings

    # Determine description and build keyboard based on the settings state
    # (either updated or original if service call failed and restored it)
    if current_settings_for_keyboard.mute_list_mode == MuteListMode.blacklist:
        current_mode_desc = _(
            "Current mode is Blacklist. You receive notifications from everyone except those on the list."
        )
    else:
        current_mode_desc = _("Current mode is Whitelist. You only receive notifications from users on the list.")

    menu_text = _("Manage Mute List\n\n{current_mode_description}").format(current_mode_description=current_mode_desc)
    updated_keyboard_markup = await create_manage_muted_users_keyboard(translator, current_settings_for_keyboard)

    if isinstance(callback_query.message, Message):
        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=menu_text,
            reply_markup=updated_keyboard_markup.as_markup(),  # Corrected: use the markup
            logger_instance=logger,
            log_context="cq_set_mute_mode_action (after service call)",
        )
    else:
        logger.warning(
            "cq_set_mute_mode_action: Message None/inaccessible for user %s after service call. UI not updated. CB: %s",
            callback_query.from_user.id if callback_query.from_user else "Unknown",
            callback_data.pack() if callback_data else callback_query.data,
        )


@mute_router.callback_query(
    UserListCallback.filter(F.action.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]))
)
async def cq_list_internal_users_action(
    callback_query: CallbackQuery,
    session: SQLAlchemyAsyncSession,  # Explicitly SQLAlchemy's session
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: UserListCallback,
) -> None:
    """Displays the first page of the internal muted/allowed user list."""
    _ = translator.gettext
    await callback_query.answer()
    await _display_internal_user_list(
        callback_query,
        translator,
        user_settings,
        callback_data.action,
        0,
        cast(SQLModelAsyncSession, session),
    )


@mute_router.callback_query(
    PaginateUsersCallback.filter(F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]))
)
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery,
    session: SQLAlchemyAsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: PaginateUsersCallback,
) -> None:
    """Handles pagination for the internal muted/allowed user list."""
    _ = translator.gettext
    await callback_query.answer()
    await _display_internal_user_list(
        callback_query,
        translator,
        user_settings,
        callback_data.list_type,
        callback_data.page,
        cast(SQLModelAsyncSession, session),
    )


@mute_router.callback_query(UserListCallback.filter(F.action == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_show_all_accounts_list_action(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
) -> None:
    """Displays the first page of all TeamTalk server accounts for muting/unmuting."""
    _ = translator.gettext
    await callback_query.answer()
    if not tt_connection:
        await callback_query.answer(_("TeamTalk connection is not available. Please try again later."), show_alert=True)
        return
    await _display_all_server_accounts_list(callback_query, translator, user_settings, tt_connection, 0)


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type == UserListAction.LIST_ALL_ACCOUNTS))
async def cq_paginate_all_accounts_list_action(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: PaginateUsersCallback,
) -> None:
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
    session: SQLAlchemyAsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: ToggleMuteSpecificCallback,
    services: "Services",
) -> None:
    """Handles the action of toggling the mute status for a specific user."""
    _ = translator.gettext
    if not tt_connection:  # Should be caught by middleware, but good check
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
            callback_query.from_user.id,
            callback_data,
        )
        await callback_query.answer(_("Error determining user to mute/unmute. Try again."), show_alert=True)
        return

    # --- Call the service function to handle all logic ---
    # N.B. user_settings object will be modified by the service if successful (due to session.refresh)
    # or if it directly manipulates the list and it's part of the same session.
    # The UserSettingsMiddleware should provide a session-attached object.
    was_successful, resulting_action = await user_service.toggle_mute_status_for_tt_user(
        cast(SQLModelAsyncSession, session), user_settings, username_to_toggle, services
    )
    # ----------------------------------------------------

    if not was_successful:
        await callback_query.answer(_("Error updating mute status. Try again later."), show_alert=True)
        return

    # Generate toast message based on the action performed by the service
    if resulting_action == "muted":
        toast_message = _generate_mute_toggle_toast_message(
            username_to_toggle, was_added_to_list=True, current_mode=user_settings.mute_list_mode, translator=translator
        )
    elif resulting_action == "unmuted":
        toast_message = _generate_mute_toggle_toast_message(
            username_to_toggle,
            was_added_to_list=False,
            current_mode=user_settings.mute_list_mode,
            translator=translator,
        )
    else:  # Should not happen if was_successful is True
        logger.error("toggle_mute_status_for_tt_user reported success but no valid resulting_action.")
        toast_message = _("Mute status updated.")

    await callback_query.answer(toast_message, show_alert=False)

    # UI refresh still needs the potentially updated user_settings from the service call
    await _refresh_mute_related_ui(callback_query, translator, user_settings, tt_connection, callback_data, session)
