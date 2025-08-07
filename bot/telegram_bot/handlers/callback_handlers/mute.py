"""Callback query handlers for mute list management and user muting/unmuting."""

from collections.abc import Awaitable, Callable
from gettext import NullTranslations
import logging
from typing import Any, TypeVar, cast

from aiogram import F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka
import pytalk

from bot.constants import USERS_PER_PAGE
from bot.core.enums import (
    Actor,
    NotificationControl,
    UserListAction,
)
from bot.models import MuteListMode, UserSettings
from bot.services.moderation_service import ModerationService
from bot.services.user_settings_service import UserSettingsService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    NotificationCallback,
    PaginateUsersCallback,
    SetMuteModeCallback,
    ToggleMuteCallback,
)
from bot.telegram_bot.keyboards import (
    create_account_list_keyboard,
    create_manage_muted_users_keyboard,
    create_paginated_user_list_keyboard,
)
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware
from bot.telegram_bot.ui_utils import display_paginated_list, paginate_list

from ._helpers import ensure_message_context, safe_edit_text

logger = logging.getLogger(__name__)
mute_router = Router(name="callback_handlers.mute")
mute_router.callback_query.middleware(
    ActiveTeamTalkConnectionMiddleware(default_server_key=None)
)
ttstr = pytalk.instance.sdk.ttstr

T = TypeVar("T")


async def _display_user_list_generic(
    callback_query: CallbackQuery,
    translator: NullTranslations,
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
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    if callback_query.bot is None:
        logger.error(
            "_display_user_list_generic: callback_query.bot is None. "
            "Cannot display list."
        )
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
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
    translator: NullTranslations,
    user_settings: UserSettings,
    list_type: UserListAction,
    page: int = 0,
) -> None:
    _ = translator.gettext

    async def fetcher() -> list[str]:
        # The user_settings object from the DI container now has this preloaded.
        return [
            muted.muted_teamtalk_username for muted in user_settings.muted_users_list
        ]

    header_text_str, empty_list_text_str = "", ""
    if user_settings.mute_list_mode == MuteListMode.blacklist:
        header_text_str = _("Blacklisted Users (Block List)")
        empty_list_text_str = _("Your blacklist is empty.")
    elif user_settings.mute_list_mode == MuteListMode.whitelist:
        header_text_str = _("Whitelisted Users (Allow List)")
        empty_list_text_str = _("Your whitelist is empty.")
    else:
        logger.error("Unknown mute_list_mode '%s'", user_settings.mute_list_mode)
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
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
        keyboard_factory_kwargs={
            "list_type": list_type,
            "user_settings": user_settings,
        },
    )


async def _display_all_server_accounts_list(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection,
    page: int = 0,
) -> None:
    _ = translator.gettext
    if not tt_connection.user_accounts_cache:
        try:
            await cast(Message, callback_query.message).edit_text(
                _(
                    "Server user accounts are not loaded yet for {server_host}. "
                    "Please try again in a moment."
                ).format(server_host=tt_connection.server_info.host)
            )
        except TelegramAPIError:
            logger.exception(
                "Error informing user about empty accounts_cache for %s.",
                tt_connection.server_info.host,
            )
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
            ttstr(acc.username).lower()
            if isinstance(acc.username, bytes)
            else str(acc.username).lower()
        ),
        title_text=_("All Server Accounts"),
        empty_list_text=_("No user accounts found on the server."),
        keyboard_factory=create_account_list_keyboard,
        keyboard_factory_kwargs={"user_settings": user_settings},
        server_host_for_display=tt_connection.server_info.host,
    )


async def _get_username_from_all_accounts(
    callback_data: ToggleMuteCallback,
    tt_connection: TeamTalkConnection,
) -> str | None:
    """Retrieves a username from the cached list of all server accounts."""
    if not tt_connection.user_accounts_cache:
        logger.warning("Cannot get username from 'all_accounts': cache empty/None.")
        return None

    all_accounts = sorted(
        tt_connection.user_accounts_cache.values(),
        key=lambda acc: (
            ttstr(acc.username).lower()
            if isinstance(acc.username, bytes)
            else str(acc.username).lower()
        ),
    )
    page_items, _, _ = paginate_list(
        all_accounts, callback_data.current_page, USERS_PER_PAGE
    )

    if 0 <= callback_data.user_idx < len(page_items):
        username_attr = page_items[callback_data.user_idx].username
        return cast(str, ttstr(username_attr)) if username_attr is not None else None
    return None


def _get_username_from_muted_list(
    callback_data: ToggleMuteCallback,
    user_settings: UserSettings,
) -> str | None:
    """Retrieves a username from the user's persisted mute list."""
    # The user_settings object from the DI container now has this preloaded.
    relevant_usernames = sorted(
        [muted.muted_teamtalk_username for muted in user_settings.muted_users_list]
    )
    page_items, _, _ = paginate_list(
        relevant_usernames, callback_data.current_page, USERS_PER_PAGE
    )

    if 0 <= callback_data.user_idx < len(page_items):
        return page_items[callback_data.user_idx]
    return None


def format_mute_toast(
    username_to_toggle: str,
    *,
    was_added_to_list: bool,
    current_mode: MuteListMode,
    translator: NullTranslations,
) -> str:
    """Formats the toast message for a mute/unmute action."""
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
    return _("{username} has been {action}.").format(
        username=quoted_username, action=action_text
    )


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    user_settings: UserSettings,
    tt_connection: TeamTalkConnection | None,
    callback_data: ToggleMuteCallback,
) -> None:
    """Refreshes the mute list UI after an action."""
    _ = translator.gettext
    list_type_user_was_on = callback_data.list_type
    current_page_for_refresh = callback_data.current_page

    # The user_settings object passed in is already the updated one from the service.
    # No need to refresh it from the session.

    if list_type_user_was_on == UserListAction.LIST_ALL_ACCOUNTS:
        if tt_connection and tt_connection.is_ready:
            await _display_all_server_accounts_list(
                callback_query,
                translator,
                user_settings,
                tt_connection,
                current_page_for_refresh,
            )
        else:
            await callback_query.answer(
                _("TeamTalk bot is disconnected. UI could not be fully refreshed."),
                show_alert=True,
            )
            manage_muted_cb_data = NotificationCallback(
                action=NotificationControl.MANAGE_MUTED
            )
            await show_manage_muted_menu(
                callback_query, translator, user_settings, manage_muted_cb_data
            )
    else:
        await _display_internal_user_list(
            callback_query,
            translator,
            user_settings,
            list_type_user_was_on,
            current_page_for_refresh,
        )


@mute_router.callback_query(
    NotificationCallback.filter(F.action == NotificationControl.MANAGE_MUTED)
)
@ensure_message_context
async def show_manage_muted_menu(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings | None],
) -> None:
    """Shows the main menu for managing muted users and mute list mode."""
    _ = translator.gettext
    if not user_settings:
        logger.warning(
            "Cannot show manage muted menu for event without a user, "
            "user_settings is None."
        )
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    manage_muted_builder = await create_manage_muted_users_keyboard(
        translator, user_settings
    )
    if user_settings.mute_list_mode == MuteListMode.blacklist:
        current_mode_text = _(
            "Current mode is Blacklist. You receive notifications from everyone "
            "except those on the list."
        )
    else:
        current_mode_text = _(
            "Current mode is Whitelist. You only receive notifications "
            "from users on the list."
        )
    full_text = _("Manage Mute List\n\n{current_mode_description}").format(
        current_mode_description=current_mode_text
    )

    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=full_text,
        reply_markup=manage_muted_builder.as_markup(),
        logger_instance=logger,
        log_context="cq_show_manage_muted_menu",
    )


@mute_router.callback_query(SetMuteModeCallback.filter())
@ensure_message_context
async def set_mute_mode(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings],
    callback_data: SetMuteModeCallback,
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    """Handles the action of setting the mute list mode (blacklist/whitelist)."""
    _ = translator.gettext
    new_mode = callback_data.mode

    updated_user_settings = await user_settings_service.update_mute_mode(
        user_settings, new_mode, actor=Actor.USER
    )

    if not updated_user_settings:
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        current_settings_for_keyboard = user_settings
    else:
        mode_text = (
            _("Blacklist")
            if updated_user_settings.mute_list_mode == MuteListMode.blacklist
            else _("Whitelist")
        )
        success_toast_text = _("Mute list mode set to {mode}.").format(mode=mode_text)
        await callback_query.answer(success_toast_text)
        current_settings_for_keyboard = updated_user_settings

    if current_settings_for_keyboard.mute_list_mode == MuteListMode.blacklist:
        current_mode_desc = _(
            "Current mode is Blacklist. You receive notifications from everyone "
            "except those on the list."
        )
    else:
        current_mode_desc = _(
            "Current mode is Whitelist. You only receive notifications "
            "from users on the list."
        )

    menu_text = _("Manage Mute List\n\n{current_mode_description}").format(
        current_mode_description=current_mode_desc
    )
    updated_keyboard_markup = await create_manage_muted_users_keyboard(
        translator, current_settings_for_keyboard
    )

    await safe_edit_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=menu_text,
        reply_markup=updated_keyboard_markup.as_markup(),
        logger_instance=logger,
        log_context="cq_set_mute_mode_action (after service call)",
    )


@mute_router.callback_query(
    PaginateUsersCallback.filter(
        F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])
    )
)
@ensure_message_context
async def display_internal_user_list(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings],
    callback_data: PaginateUsersCallback,
) -> None:
    """Handles pagination for the internal muted/allowed user list."""
    await _display_internal_user_list(
        callback_query,
        translator,
        user_settings,
        callback_data.list_type,
        callback_data.page,
    )


@mute_router.callback_query(
    PaginateUsersCallback.filter(F.list_type == UserListAction.LIST_ALL_ACCOUNTS)
)
@ensure_message_context
async def display_all_accounts_list(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings | None],
    tt_connection: FromDishka[TeamTalkConnection | None],
    callback_data: PaginateUsersCallback,
) -> None:
    """Handles pagination for the list of all TeamTalk server accounts."""
    if not user_settings:
        _ = translator.gettext
        logger.warning(
            "Cannot display all accounts list for event without a user, "
            "user_settings is None."
        )
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    if not tt_connection:
        _ = translator.gettext
        await callback_query.answer(
            _("TeamTalk connection is not active."), show_alert=True
        )
        return
    await _display_all_server_accounts_list(
        callback_query, translator, user_settings, tt_connection, callback_data.page
    )


@mute_router.callback_query(ToggleMuteCallback.filter())
@ensure_message_context
async def toggle_user_mute(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings],
    tt_connection: FromDishka[TeamTalkConnection | None],
    callback_data: ToggleMuteCallback,
    moderation_service: FromDishka[ModerationService],
) -> None:
    """Handles the action of toggling the mute status for a specific user."""
    _ = translator.gettext
    username_to_toggle = None
    list_type = callback_data.list_type

    if list_type == UserListAction.LIST_ALL_ACCOUNTS:
        if tt_connection:
            username_to_toggle = await _get_username_from_all_accounts(
                callback_data, tt_connection
            )
    elif list_type in [UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED]:
        username_to_toggle = _get_username_from_muted_list(callback_data, user_settings)

    if not username_to_toggle:
        logger.warning(
            "Could not determine username to toggle mute for user %s. "
            "Callback data: %s",
            callback_query.from_user.id,
            callback_data,
        )
        await callback_query.answer(
            _("Error determining user to mute/unmute. Try again."), show_alert=True
        )
        return

    result = await moderation_service.toggle_mute_status(
        user_settings, username_to_toggle, translator
    )

    toast_message = translator.gettext(result.message_key).format(
        **(result.message_args or {})
    )
    await callback_query.answer(toast_message, show_alert=not result.success)

    if result.success and result.user_settings:
        await _refresh_mute_related_ui(
            callback_query,
            translator,
            result.user_settings,
            tt_connection,
            callback_data,
        )
