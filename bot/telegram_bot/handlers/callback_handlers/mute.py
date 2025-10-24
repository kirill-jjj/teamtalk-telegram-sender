"""Callback query handlers for mute list management and user muting/unmuting."""

from gettext import NullTranslations
import logging
from typing import Annotated, Any, TypeVar

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.config import Settings
from bot.core.enums import (
    Actor,
    NotificationControl,
    UserListAction,
)
from bot.database.uow import IUnitOfWork
from bot.models import MuteListMode, UserSettings
from bot.services.moderation_service import ModerationService
from bot.services.report_service import ReportService
from bot.services.schemas import SettingsViewDTO
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import (
    NotificationCallback,
    PaginateUsersCallback,
    SetMuteModeCallback,
    ToggleMuteCallback,
)
from bot.telegram_bot.formatters import (
    format_manage_muted_menu_text,
    format_mute_toast,
)
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.keyboards import create_manage_muted_users_keyboard
from bot.telegram_bot.ui_utils import (
    _display_user_list,
    edit_message_text,
)

logger = logging.getLogger(__name__)
mute_router = Router(name="callback_handlers.mute")


T = TypeVar("T")


async def _display_internal_user_list(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    user_settings: UserSettings,
    report_service: ReportService,  # Add service dependency
    list_type: UserListAction,
    page: int = 0,
) -> None:
    _ = translator.gettext

    view_data = report_service.prepare_mute_list_view_data(user_settings, translator)
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
            ),
            "back_button_destination": _("Mute Management"),
        },
    )


async def _show_all_accounts_list(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    user_settings: UserSettings,
    report_service: ReportService,
    page: int,
) -> None:
    """Displays a paginated list of all TeamTalk server accounts."""
    _ = translator.gettext
    view_data = await report_service.get_all_server_accounts_view_data(
        lang_code=translator.info().get("language", "en"), translator=translator
    )
    muted_usernames = {
        user.muted_teamtalk_username for user in user_settings.muted_users_list
    }

    await _display_user_list(
        callback_query=callback_query,
        translator=translator,
        page=page,
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
            ),
            "back_button_destination": _("Mute Management"),
        },
    )
    await callback_query.answer()


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    user_settings: UserSettings,
    command_bus: CommandBus,
    report_service: ReportService,
    moderation_service: ModerationService,
    callback_data: ToggleMuteCallback,
) -> None:
    """Refreshes the mute list UI after an action."""
    list_type_user_was_on = callback_data.list_type
    current_page_for_refresh = callback_data.current_page

    if list_type_user_was_on == UserListAction.LIST_ALL_ACCOUNTS:
        await _show_all_accounts_list(
            callback_query=callback_query,
            translator=translator,
            user_settings=user_settings,
            report_service=report_service,
            page=current_page_for_refresh,
        )
    else:
        await _display_internal_user_list(
            callback_query,
            translator,
            user_settings,
            report_service,
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
    user_settings: FromDishka[SettingsViewDTO | None],
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

    manage_muted_builder = create_manage_muted_users_keyboard(translator, user_settings)
    full_text = format_manage_muted_menu_text(translator, user_settings.mute_list_mode)

    await edit_message_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=full_text,
        reply_markup=manage_muted_builder.as_markup(),
    )
    await callback_query.answer()


async def refresh_manage_muted_menu(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    user_settings: SettingsViewDTO,
    **kwargs: Any,
) -> None:
    """Refresher function for the manage muted menu."""
    await show_manage_muted_menu(callback_query, translator, user_settings)
    await show_manage_muted_menu(callback_query, translator, user_settings)


@mute_router.callback_query(SetMuteModeCallback.filter())
@ensure_message_context
async def set_mute_mode(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    callback_data: SetMuteModeCallback,
    user_settings_service: FromDishka[UserSettingsService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Handles the action of setting the mute list mode (blacklist/whitelist)."""
    _ = translator.gettext
    new_mode = callback_data.mode

    async with uow:
        user_settings = await user_settings_service.get_or_create(
            uow, callback_query.from_user.id, "en"
        )
        if new_mode.value == user_settings.mute_list_mode:
            await callback_query.answer()
            return

        updated_user_settings = await user_settings_service.update_mute_mode(
            uow,
            telegram_id=callback_query.from_user.id,
            new_mode=new_mode,
            actor=Actor.USER,
        )
        await uow.commit()

    if not updated_user_settings:
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    mode_text = (
        _("Blacklist")
        if updated_user_settings.mute_list_mode == MuteListMode.blacklist
        else _("Whitelist")
    )
    success_toast_text = _("Mute list mode set to {mode}.").format(mode=mode_text)
    await callback_query.answer(success_toast_text)
    user_settings_dto = SettingsViewDTO(
        language_code=updated_user_settings.language_code,
        notification_settings=updated_user_settings.notification_settings,
        mute_list_mode=updated_user_settings.mute_list_mode,
        not_on_online_enabled=updated_user_settings.not_on_online_enabled,
        teamtalk_username=updated_user_settings.teamtalk_username,
        muted_users_count=len(updated_user_settings.muted_users_list),
    )
    await refresh_manage_muted_menu(callback_query, translator, user_settings_dto)


@mute_router.callback_query(
    PaginateUsersCallback.filter(
        F.list_type.in_([UserListAction.LIST_MUTED, UserListAction.LIST_ALLOWED])
    )
)
@ensure_message_context
async def display_internal_user_list(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    user_settings_service: FromDishka[UserSettingsService],
    settings: FromDishka[Settings],
    report_service: FromDishka[ReportService],
    callback_data: PaginateUsersCallback,
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Handles pagination for the internal muted/allowed user list."""
    async with uow:
        user_settings = await user_settings_service.get_or_create(
            uow, callback_query.from_user.id, settings.general.default_lang
        )
    await _display_internal_user_list(
        callback_query,
        translator,
        user_settings,
        report_service,
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
    user_settings_service: FromDishka[UserSettingsService],
    settings: FromDishka[Settings],
    report_service: FromDishka[ReportService],
    callback_data: PaginateUsersCallback,
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Handles pagination for the list of all TeamTalk server accounts."""
    async with uow:
        user_settings = await user_settings_service.get_or_create(
            uow, callback_query.from_user.id, settings.general.default_lang
        )
    await _show_all_accounts_list(
        callback_query=callback_query,
        translator=translator,
        user_settings=user_settings,
        report_service=report_service,
        page=callback_data.page,
    )


@mute_router.callback_query(ToggleMuteCallback.filter())
@ensure_message_context
async def toggle_user_mute(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    command_bus: FromDishka[CommandBus],
    callback_data: ToggleMuteCallback,
    moderation_service: FromDishka[ModerationService],
    report_service: FromDishka[ReportService],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Handles the action of toggling the mute status for a specific user."""
    async with uow:
        toggle_result = await moderation_service.toggle_mute_from_paginated_list(
            uow,
            telegram_id=callback_query.from_user.id,
            list_type=callback_data.list_type,
            page=callback_data.current_page,
            index_on_page=callback_data.user_idx,
            command_bus=command_bus,
            translator=translator,
        )
        await uow.commit()

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
            report_service,  # Pass the report service
            moderation_service,  # Pass the moderation service
            callback_data,
        )
