"""Callback query handlers for mute list management and user muting/unmuting."""

from collections.abc import Callable
from gettext import NullTranslations
import logging
from typing import Any, TypeVar

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.constants import MSG_GENERAL_ERROR, USERS_PER_PAGE
from bot.core.enums import (
    Actor,
    NotificationControl,
    UserListAction,
)
from bot.models import MuteListMode, UserSettings
from bot.services.moderation_service import ModerationService
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import (
    NotificationCallback,
    PaginateUsersCallback,
    SetMuteModeCallback,
    ToggleMuteCallback,
)
from bot.telegram_bot.formatters import format_mute_toast  # Added import
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import create_manage_muted_users_keyboard
from bot.telegram_bot.keyboards.shared import (
    _create_back_button_text,
    create_toggle_mute_keyboard,
)
from bot.telegram_bot.ui_utils import (
    display_paginated_list,
    safe_edit_text,
)
from bot.utils.pagination import paginate_list

logger = logging.getLogger(__name__)
mute_router = Router(name="callback_handlers.mute")


T = TypeVar("T")


async def _display_user_list(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    page: int,
    items: list[Any],
    sort_key_extractor: Callable[[Any], Any],
    title_text: str,
    empty_list_text: str,
    keyboard_factory_kwargs: dict[str, Any],
    server_host_for_display: str | None = None,
) -> None:
    """A generic helper to display a paginated list of users."""
    _ = translator.gettext
    sorted_items = sorted(items, key=sort_key_extractor)

    if callback_query.bot is None:
        logger.error("Cannot display user list: bot is None.")
        await callback_query.answer(_(MSG_GENERAL_ERROR), show_alert=True)
        return

    page_slice, _total_pages, current_page_idx = paginate_list(
        sorted_items, page, USERS_PER_PAGE
    )

    await display_paginated_list(
        target=callback_query,
        bot=callback_query.bot,
        translator=translator,
        items_on_page=page_slice,
        total_items=len(sorted_items),
        page=current_page_idx,
        title_text=title_text,
        empty_list_text=empty_list_text,
        keyboard_factory=create_toggle_mute_keyboard,
        keyboard_factory_kwargs=keyboard_factory_kwargs,
        page_size=USERS_PER_PAGE,
        server_host_for_display=server_host_for_display,
    )


async def _display_internal_user_list(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    user_settings: UserSettings,
    moderation_service: ModerationService,  # Add service dependency
    list_type: UserListAction,
    page: int = 0,
) -> None:
    _ = translator.gettext

    view_data = moderation_service.prepare_mute_list_view_data(
        user_settings, translator
    )
    muted_usernames = {
        user.muted_teamtalk_username for user in user_settings.muted_users_list
    }

    await _display_user_list(
        callback_query=callback_query,
        translator=translator,
        page=page,
        items=view_data.items,
        # Sorting is now done in service, but helper still needs it
        sort_key_extractor=lambda x: x.lower(),
        title_text=view_data.title,
        empty_list_text=view_data.empty_list_text,
        keyboard_factory_kwargs={
            "mute_list_mode": user_settings.mute_list_mode,
            "muted_usernames": muted_usernames,
            "list_type_for_callback": list_type,
            "item_username_extractor": lambda item: item,
            "item_display_name_extractor": lambda item: item,
            "back_button_callback_data": NotificationCallback(
                action=NotificationControl.MANAGE_MUTED
            ).pack(),
            "back_button_text_key": _create_back_button_text(
                translator, _("Mute Management")
            ),
        },
    )


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    user_settings: UserSettings,
    command_bus: CommandBus,
    moderation_service: ModerationService,  # Add missing parameter
    callback_data: ToggleMuteCallback,
) -> None:
    """Refreshes the mute list UI after an action."""
    _ = translator.gettext
    list_type_user_was_on = callback_data.list_type
    current_page_for_refresh = callback_data.current_page

    # The user_settings object passed in is already the updated one from the service.
    # No need to refresh it from the session.

    if list_type_user_was_on == UserListAction.LIST_ALL_ACCOUNTS:
        await display_all_accounts_list(
            callback_query,
            translator,
            user_settings,
            moderation_service,  # This needs to be passed
            PaginateUsersCallback(
                list_type=UserListAction.LIST_ALL_ACCOUNTS,
                page=current_page_for_refresh,
            ),
        )
    else:
        await _display_internal_user_list(
            callback_query,
            translator,
            user_settings,
            moderation_service,  # Pass the service
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
        await callback_query.answer(_(MSG_GENERAL_ERROR), show_alert=True)
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
    )
    await callback_query.answer()


async def refresh_manage_muted_menu(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    user_settings: UserSettings,
    **kwargs: Any,
) -> None:
    """Refresher function for the manage muted menu."""
    await show_manage_muted_menu(callback_query, translator, user_settings)


@mute_router.callback_query(SetMuteModeCallback.filter())
@ensure_message_context
async def set_mute_mode(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    callback_data: SetMuteModeCallback,
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    """Handles the action of setting the mute list mode (blacklist/whitelist)."""
    _ = translator.gettext
    new_mode = callback_data.mode

    user_settings = await user_settings_service.get_or_create(
        callback_query.from_user.id, "en"
    )
    if new_mode.value == user_settings.mute_list_mode:
        await callback_query.answer()
        return

    updated_user_settings = await user_settings_service.update_mute_mode(
        telegram_id=callback_query.from_user.id, new_mode=new_mode, actor=Actor.USER
    )

    if not updated_user_settings:
        await callback_query.answer(_(MSG_GENERAL_ERROR), show_alert=True)
        return

    mode_text = (
        _("Blacklist")
        if updated_user_settings.mute_list_mode == MuteListMode.blacklist
        else _("Whitelist")
    )
    success_toast_text = _("Mute list mode set to {mode}.").format(mode=mode_text)
    await callback_query.answer(success_toast_text)
    await refresh_manage_muted_menu(callback_query, translator, updated_user_settings)


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
    moderation_service: FromDishka[ModerationService],
    callback_data: PaginateUsersCallback,
) -> None:
    """Handles pagination for the internal muted/allowed user list."""
    await _display_internal_user_list(
        callback_query,
        translator,
        user_settings,
        moderation_service,
        callback_data.list_type,
        callback_data.page,
    )
    await callback_query.answer()


@mute_router.callback_query(
    PaginateUsersCallback.filter(F.list_type == UserListAction.LIST_ALL_ACCOUNTS)
)
@ensure_message_context
async def display_all_accounts_list(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings: FromDishka[UserSettings],
    moderation_service: FromDishka[ModerationService],
    callback_data: PaginateUsersCallback,
) -> None:
    """Handles pagination for the list of all TeamTalk server accounts."""
    _ = translator.gettext
    view_data = await moderation_service.get_all_server_accounts_view_data(
        lang_code=translator.info().get("language", "en"), translator=translator
    )
    muted_usernames = {
        user.muted_teamtalk_username for user in user_settings.muted_users_list
    }

    await _display_user_list(
        callback_query=callback_query,
        translator=translator,
        page=callback_data.page,
        items=view_data.accounts,
        sort_key_extractor=lambda acc: acc.username.lower(),
        title_text=view_data.title,
        empty_list_text=view_data.empty_list_text,
        keyboard_factory_kwargs={
            "mute_list_mode": user_settings.mute_list_mode,
            "muted_usernames": muted_usernames,
            "list_type_for_callback": UserListAction.LIST_ALL_ACCOUNTS,
            "item_username_extractor": lambda item: item.username,
            "item_display_name_extractor": lambda item: item.username,
            "back_button_callback_data": NotificationCallback(
                action=NotificationControl.MANAGE_MUTED
            ).pack(),
            "back_button_text_key": _create_back_button_text(
                translator, _("Mute Management")
            ),
        },
    )
    await callback_query.answer()


@mute_router.callback_query(ToggleMuteCallback.filter())
@ensure_message_context
async def toggle_user_mute(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    command_bus: FromDishka[CommandBus],
    callback_data: ToggleMuteCallback,
    moderation_service: FromDishka[ModerationService],
) -> None:
    """Handles the action of toggling the mute status for a specific user."""
    toggle_result = await moderation_service.toggle_mute_from_callback(
        callback_data,
        callback_query.from_user.id,
        command_bus,
        translator,
    )

    toast_message = format_mute_toast(
        username_to_toggle=toggle_result.message_args["username"]
        if toggle_result.message_args
        else "",
        was_added_to_list=toggle_result.message_key
        == translator.gettext("User {username} has been successfully muted."),
        current_mode=toggle_result.user_settings.mute_list_mode
        if toggle_result.user_settings
        else MuteListMode.blacklist,  # Default to blacklist if None
        translator=translator,
    )
    await callback_query.answer(toast_message, show_alert=not toggle_result.success)

    if toggle_result.success and toggle_result.user_settings:
        await _refresh_mute_related_ui(
            callback_query,
            translator,
            toggle_result.user_settings,
            command_bus,
            moderation_service,
            callback_data,
        )
