"""Callback query handlers for mute list management and user muting/unmuting."""

from collections.abc import Awaitable, Callable
import gettext
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    TypeVar,
    cast,
)

from aiogram import F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
import pytalk
from sqlmodel import select

# Import SQLModel's AsyncSession and alias the other one if needed, or just use one consistently.
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from bot.constants import USERS_PER_PAGE
from bot.core.enums import (
    NotificationAction,
    ToggleMuteSpecificAction,
    UserListAction,
)
from bot.locales.keys import MSG_KEY_GENERIC_ERROR
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
from bot.telegram_bot.ui_utils import display_paginated_list, paginate_list

from ._helpers import ensure_message_context, safe_edit_text

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
mute_router = Router(name="callback_handlers.mute")
mute_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
mute_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())
ttstr = pytalk.instance.sdk.ttstr

T = TypeVar("T")


async def _display_user_list_generic(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    page: int,
    data_fetcher: Callable[[], Awaitable[list[Any]]],
    sort_key_extractor: Callable[[Any], str],
    title_text: str,
    empty_list_text: str,
    keyboard_factory: Callable[..., Awaitable[Any]],
    keyboard_factory_kwargs: dict[str, Any],
    server_host_for_display: str | None = None,
) -> None:
    _ = translator.gettext
    try:
        items = await data_fetcher()
        sorted_items = sorted(items, key=sort_key_extractor)
    except Exception:
        logger.exception("Failed to fetch or sort user list.")
        await callback_query.answer(_(MSG_KEY_GENERIC_ERROR), show_alert=True)
        return

    if callback_query.bot is None:
        logger.error("_display_user_list_generic: callback_query.bot is None. Cannot display list.")
        await callback_query.answer(
            _("An error occurred while displaying the list. Bot instance not found."), show_alert=True
        )
        return

    await display_paginated_list(
        target=callback_query,
        bot=callback_query.bot,
        translator=translator,
        items=sorted_items,
        page=page,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=keyboard_factory,
        keyboard_factory_kwargs=keyboard_factory_kwargs,
        server_host_for_display=server_host_for_display,
    )


async def _display_internal_user_list(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    list_type: UserListAction,
    page: int = 0,
    session: SQLModelAsyncSession | None = None,
) -> None:
    _ = translator.gettext
    if not session:
        logger.error("Session not provided to _display_internal_user_list")
        await callback_query.answer(_(MSG_KEY_GENERIC_ERROR), show_alert=True)
        return

    async def fetcher() -> list[str]:
        statement = select(MutedUser.muted_teamtalk_username).where(
            MutedUser.user_settings_telegram_id == user_settings.telegram_id
        )
        results = await session.exec(statement)
        return [str(username) for username in results.all()]

    header_text_str, empty_list_text_str = "", ""
    if user_settings.mute_list_mode == MuteListMode.blacklist:
        header_text_str = _("Blacklisted Users (Block List)")
        empty_list_text_str = _("Your blacklist is empty.")
    elif user_settings.mute_list_mode == MuteListMode.whitelist:
        header_text_str = _("Whitelisted Users (Allow List)")
        empty_list_text_str = _("Your whitelist is empty.")
    else:
        logger.error("Unknown mute_list_mode '%s'", user_settings.mute_list_mode)
        await callback_query.answer(_(MSG_KEY_GENERIC_ERROR), show_alert=True)
        return

    await _display_user_list_generic(
        callback_query=callback_query,
        translator=translator,
        user_settings=user_settings,
        page=page,
        data_fetcher=fetcher,
        sort_key_extractor=lambda x: x.lower(),
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
    if not tt_connection.user_accounts_cache:
        try:
            await cast(Message, callback_query.message).edit_text(
                _("Server user accounts are not loaded yet for {server_host}. Please try again in a moment.").format(
                    server_host=tt_connection.server_info.host
                )
            )
        except TelegramAPIError:
            logger.exception("Error informing user about empty accounts_cache for %s.", tt_connection.server_info.host)
        return

    async def fetcher() -> list[pytalk.UserAccount]:
        return list(tt_connection.user_accounts_cache.values())

    await _display_user_list_generic(
        callback_query=callback_query,
        translator=translator,
        user_settings=user_settings,
        page=page,
        data_fetcher=fetcher,
        sort_key_extractor=lambda acc: (
            ttstr(acc.username).lower() if isinstance(acc.username, bytes) else str(acc.username).lower()
        ),
        title_text=_("All Server Accounts"),
        empty_list_text=_("No user accounts found on the server."),
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={"user_settings": user_settings},
        server_host_for_display=tt_connection.server_info.host,
    )


async def _get_username_to_toggle_from_callback(
    callback_data: ToggleMuteSpecificCallback,
    user_settings: UserSettings,
    session: SQLModelAsyncSession,  # Changed to SQLModel's AsyncSession
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
        page_items, _, _ = paginate_list(all_accounts, current_page, USERS_PER_PAGE)
        if 0 <= user_idx < len(page_items):
            username_attr = page_items[user_idx].username
            # Assuming ttstr handles bytes and returns str. If username_attr can be None, handle it.
            return cast(str, ttstr(username_attr)) if username_attr is not None else None
    elif list_type in [UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]:
        statement = select(MutedUser.muted_teamtalk_username).where(
            MutedUser.user_settings_telegram_id == user_settings.telegram_id
        )
        results = await session.exec(statement)  # Changed to session.exec for SQLModel
        # SQLModel's exec results directly give items
        relevant_usernames = sorted([str(uname) for uname in results.all()])
        page_items, _, _ = paginate_list(relevant_usernames, current_page, USERS_PER_PAGE)
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
    session: SQLModelAsyncSession,  # Changed to SQLModel's AsyncSession
) -> None:
    """Refreshes the mute list UI after an action."""
    _ = translator.gettext
    list_type_user_was_on = callback_data.list_type
    current_page_for_refresh = callback_data.current_page

    # The calling handler (cq_toggle_specific_user_mute_action) is decorated with @ensure_message_context,
    # so callback_query.message is guaranteed to be a Message object here.
    try:
        await session.refresh(user_settings, attribute_names=["muted_users_list"])
        logger.debug("Refreshed muted_users_list for user %s before UI refresh.", user_settings.telegram_id)
    except Exception:
        logger.exception("Failed to refresh user_settings relations for %s.", user_settings.telegram_id)
        await callback_query.answer(_(MSG_KEY_GENERIC_ERROR), show_alert=True)
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
            session,  # No longer need to cast
        )


@mute_router.callback_query(NotificationActionCallback.filter(F.action == NotificationAction.MANAGE_MUTED))
@ensure_message_context
async def cq_show_manage_muted_menu(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    _callback_data: NotificationActionCallback | None = None,  # Keep for consistent signature, though not used
) -> None:
    """Shows the main menu for managing muted users and mute list mode."""
    _ = translator.gettext
    # Callback answering handled by decorator or safe_edit_text.
    manage_muted_builder = await create_manage_muted_users_keyboard(translator, user_settings)
    if user_settings.mute_list_mode == MuteListMode.blacklist:
        current_mode_text = _(
            "Current mode is Blacklist. You receive notifications from everyone except those on the list."
        )
    else:
        current_mode_text = _("Current mode is Whitelist. You only receive notifications from users on the list.")
    full_text = _("Manage Mute List\n\n{current_mode_description}").format(current_mode_description=current_mode_text)

    # Decorator ensures callback_query.message is a Message object.
    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=full_text,
        reply_markup=manage_muted_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_manage_muted_menu",
    )


@mute_router.callback_query(SetMuteModeCallback.filter())
@ensure_message_context
async def cq_set_mute_mode_action(
    callback_query: CallbackQuery,
    session: SQLModelAsyncSession,  # Changed to SQLModel's AsyncSession
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: SetMuteModeCallback,
    services: "Services",
) -> None:
    """Handles the action of setting the mute list mode (blacklist/whitelist)."""
    _ = translator.gettext
    # Decorator ensures callback_query.message exists.

    new_mode = callback_data.mode

    # The user_settings object from middleware should already be session-managed.
    # The service function `set_user_mute_mode` will handle merging if necessary,
    # committing, cache updates, and error handling.
    updated_user_settings = await user_service.set_user_mute_mode(session, services, user_settings, new_mode)

    if not updated_user_settings:
        # Service function handles logging and rollback.
        # Inform user of failure. The user_settings object might be in its original state
        # or state before the failed commit attempt if service function restored it.
        await callback_query.answer(_(MSG_KEY_GENERIC_ERROR), show_alert=True)
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

    # Decorator ensures callback_query.message is a Message object.
    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=menu_text,
        reply_markup=updated_keyboard_markup.as_markup(),
        logger_instance=logger,
        log_context="cq_set_mute_mode_action (after service call)",
    )


@mute_router.callback_query(
    UserListCallback.filter(F.action.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]))
)
@ensure_message_context
async def cq_list_internal_users_action(
    callback_query: CallbackQuery,
    session: SQLModelAsyncSession,  # Changed to SQLModel's AsyncSession
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: UserListCallback,
) -> None:
    """Displays the first page of the internal muted/allowed user list."""
    _ = translator.gettext
    # Callback answering handled by decorator or _display_internal_user_list.
    await _display_internal_user_list(
        callback_query,
        translator,
        user_settings,
        callback_data.action,
        0,
        session,  # No longer need to cast
    )


@mute_router.callback_query(
    PaginateUsersCallback.filter(F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]))
)
@ensure_message_context
async def cq_paginate_internal_user_list_action(
    callback_query: CallbackQuery,
    session: SQLModelAsyncSession,  # Changed to SQLModel's AsyncSession
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    callback_data: PaginateUsersCallback,
) -> None:
    """Handles pagination for the internal muted/allowed user list."""
    _ = translator.gettext
    # Callback answering handled by decorator or _display_internal_user_list.
    await _display_internal_user_list(
        callback_query,
        translator,
        user_settings,
        callback_data.list_type,
        callback_data.page,
        session,  # No longer need to cast
    )


@mute_router.callback_query(UserListCallback.filter(F.action == UserListAction.LIST_ALL_ACCOUNTS))
@ensure_message_context
async def cq_show_all_accounts_list_action(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
) -> None:
    """Displays the first page of all TeamTalk server accounts for muting/unmuting."""
    _ = translator.gettext
    # Callback answering handled by decorator or _display_all_server_accounts_list.
    # The TeamTalkConnectionCheckMiddleware ensures tt_connection is valid.
    # Decorator ensures callback_query.message exists.
    await _display_all_server_accounts_list(
        callback_query, translator, user_settings, cast(TeamTalkConnection, tt_connection), 0
    )


@mute_router.callback_query(PaginateUsersCallback.filter(F.list_type == UserListAction.LIST_ALL_ACCOUNTS))
@ensure_message_context
async def cq_paginate_all_accounts_list_action(
    callback_query: CallbackQuery,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: PaginateUsersCallback,
) -> None:
    """Handles pagination for the list of all TeamTalk server accounts."""
    _ = translator.gettext
    # Callback answering handled by decorator or _display_all_server_accounts_list.
    # The TeamTalkConnectionCheckMiddleware ensures tt_connection is valid.
    # Decorator ensures callback_query.message exists.
    await _display_all_server_accounts_list(
        callback_query, translator, user_settings, cast(TeamTalkConnection, tt_connection), callback_data.page
    )


@mute_router.callback_query(ToggleMuteSpecificCallback.filter(F.action == ToggleMuteSpecificAction.TOGGLE_USER))
@ensure_message_context
async def cq_toggle_specific_user_mute_action(
    callback_query: CallbackQuery,
    session: SQLModelAsyncSession,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: ToggleMuteSpecificCallback,
    services: "Services",
) -> None:
    """Handles the action of toggling the mute status for a specific user."""
    _ = translator.gettext
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

    result = await user_service.toggle_mute_status_for_tt_user(session, user_settings, username_to_toggle, services)

    toast_message = _(result.message_key).format(**(result.message_args or {}))
    await callback_query.answer(toast_message, show_alert=not result.success)

    if result.success and result.user_settings:
        await _refresh_mute_related_ui(
            callback_query, translator, result.user_settings, tt_connection, callback_data, session
        )
