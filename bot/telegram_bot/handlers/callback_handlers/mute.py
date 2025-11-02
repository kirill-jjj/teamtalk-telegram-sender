"""Callback query handlers for mute list management and user muting/unmuting."""

from gettext import NullTranslations
import logging
from typing import Annotated, TypeVar, cast

from aiogram import F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka

from bot.config import Settings
from bot.core.enums import (
    Actor,
    NotificationControl,
    UserListAction,
)
from bot.database.types import MuteListMode
from bot.database.uow import IUnitOfWork
from bot.services.moderation_service import ModerationService
from bot.services.report_service import ReportService
from bot.services.schemas import ManageMutedMenuDTO, MuteListDisplayDTO
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
from bot.telegram_bot.types.bots import EventBot
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
    mute_list_display_data: MuteListDisplayDTO,
    report_service: ReportService,
    list_type: UserListAction,
    page: int = 0,
) -> None:
    _ = translator.gettext

    muted_usernames = set(mute_list_display_data.muted_usernames)

    await _display_user_list(
        callback_query=callback_query,
        translator=translator,
        page=page,
        items=mute_list_display_data.muted_usernames,
        # Sorting is now done in service, but helper still needs it
        sort_key_extractor=lambda x: x.lower(),
        title_text=_("Mute list for: {name}").format(
            name=mute_list_display_data.display_name
        ),
        empty_list_text=_("The mute list is currently empty."),
        keyboard_factory_kwargs={
            "mute_list_mode": mute_list_display_data.mute_list_mode,
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
    mute_list_display_data: MuteListDisplayDTO,
    report_service: ReportService,
    page: int,
) -> None:
    """Displays a paginated list of all TeamTalk server accounts."""
    _ = translator.gettext
    view_data = await report_service.get_all_server_accounts_view_data(
        lang_code=translator.info().get("language", "en"), translator=translator
    )
    muted_usernames = set(mute_list_display_data.muted_usernames)

    await _display_user_list(
        callback_query=callback_query,
        translator=translator,
        page=page,
        items=view_data.accounts,
        sort_key_extractor=lambda acc: acc.username.lower(),
        title_text=view_data.title,
        empty_list_text=view_data.empty_list_text,
        keyboard_factory_kwargs={
            "mute_list_mode": mute_list_display_data.mute_list_mode,
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


async def _refresh_mute_related_ui(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    mute_list_display_data: MuteListDisplayDTO,
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
            mute_list_display_data=mute_list_display_data,
            report_service=report_service,
            page=current_page_for_refresh,
        )
    else:
        await _display_internal_user_list(
            callback_query,
            translator,
            mute_list_display_data,
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
    user_settings_service: FromDishka[UserSettingsService],
    settings: FromDishka[Settings],
    uow: Annotated[IUnitOfWork, FromDishka()],
) -> None:
    """Shows the main menu for managing muted users and mute list mode."""
    _ = translator.gettext
    if not callback_query.from_user:
        logger.warning(
            "Cannot show manage muted menu for event without a user, "
            "user_settings is None."
        )
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    async with uow:
        manage_muted_menu_data = await user_settings_service.get_manage_muted_menu_data(
            uow, callback_query.from_user.id, settings.general.default_lang
        )
    if not manage_muted_menu_data:
        logger.warning(
            "Could not retrieve manage muted menu data for user %s",
            callback_query.from_user.id,
        )
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    manage_muted_builder = create_manage_muted_users_keyboard(
        translator, manage_muted_menu_data
    )
    full_text = format_manage_muted_menu_text(translator, manage_muted_menu_data)

    await edit_message_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=full_text,
        reply_markup=manage_muted_builder.as_markup(),
    )


async def refresh_manage_muted_menu(
    callback_query: CallbackQuery,
    translator: NullTranslations,
    manage_muted_menu_data: ManageMutedMenuDTO,
    user_settings_service: UserSettingsService,
    settings: Settings,
    uow: IUnitOfWork,
) -> None:
    """Refresher function for the manage muted menu."""
    _ = translator.gettext
    # Re-fetch the data to ensure it's up-to-date
    async with uow:
        updated_manage_muted_menu_data = (
            await user_settings_service.get_manage_muted_menu_data(
                uow, callback_query.from_user.id, settings.general.default_lang
            )
        )
    if not updated_manage_muted_menu_data:
        logger.warning(
            "Could not refresh manage muted menu data for user %s",
            callback_query.from_user.id,
        )
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    manage_muted_builder = create_manage_muted_users_keyboard(
        translator, updated_manage_muted_menu_data
    )
    full_text = format_manage_muted_menu_text(
        translator, updated_manage_muted_menu_data
    )

    await edit_message_text(
        message_to_edit=callback_query.message,  # type: ignore[arg-type]
        text=full_text,
        reply_markup=manage_muted_builder.as_markup(),
    )


@mute_router.callback_query(SetMuteModeCallback.filter())
@ensure_message_context
async def set_mute_mode(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    callback_data: SetMuteModeCallback,
    user_settings_service: FromDishka[UserSettingsService],
    uow: Annotated[IUnitOfWork, FromDishka()],
    settings: FromDishka[Settings],
) -> None:
    """Handles the action of setting the mute list mode (blacklist/whitelist)."""
    _ = translator.gettext
    new_mode = callback_data.mode

    async with uow:
        user_settings = await user_settings_service.get_or_create(
            uow, callback_query.from_user.id, "en"
        )
        if new_mode.value == user_settings.mute_list_mode:
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
    manage_muted_menu_data = ManageMutedMenuDTO(
        mute_list_mode=updated_user_settings.mute_list_mode,
        not_on_online_enabled=updated_user_settings.not_on_online_enabled,
    )
    await refresh_manage_muted_menu(
        callback_query,
        translator,
        manage_muted_menu_data,
        user_settings_service,
        settings,
        uow,
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
    user_settings_service: FromDishka[UserSettingsService],
    settings: FromDishka[Settings],
    report_service: FromDishka[ReportService],
    callback_data: PaginateUsersCallback,
    uow: Annotated[IUnitOfWork, FromDishka()],
    bot: FromDishka[EventBot],
) -> None:
    """Handles pagination for the internal muted/allowed user list."""
    _ = translator.gettext
    if not callback_query.from_user:
        logger.warning("display_internal_user_list called without from_user.")
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    async with uow:
        mute_list_display_data = await user_settings_service.get_mute_list_display_data(
            uow, callback_query.from_user.id, settings.general.default_lang, bot
        )
    if not mute_list_display_data:
        logger.warning(
            "Could not retrieve mute list display data for user %s",
            callback_query.from_user.id,
        )
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    await _display_internal_user_list(
        callback_query,
        translator,
        mute_list_display_data,
        report_service,
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
    user_settings_service: FromDishka[UserSettingsService],
    settings: FromDishka[Settings],
    report_service: FromDishka[ReportService],
    callback_data: PaginateUsersCallback,
    uow: Annotated[IUnitOfWork, FromDishka()],
    bot: FromDishka[EventBot],
) -> None:
    """Handles pagination for the list of all TeamTalk server accounts."""
    _ = translator.gettext
    if not callback_query.from_user:
        logger.warning("display_all_accounts_list called without from_user.")
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    async with uow:
        mute_list_display_data = await user_settings_service.get_mute_list_display_data(
            uow, callback_query.from_user.id, settings.general.default_lang, bot
        )
    if not mute_list_display_data:
        logger.warning(
            "Could not retrieve mute list display data for user %s",
            callback_query.from_user.id,
        )
        await callback_query.answer(
            _("An error occurred. Please try again later."), show_alert=True
        )
        return

    await _show_all_accounts_list(
        callback_query=callback_query,
        translator=translator,
        mute_list_display_data=mute_list_display_data,
        report_service=report_service,
        page=callback_data.page,
    )


@mute_router.callback_query(ToggleMuteCallback.filter())
@ensure_message_context
async def toggle_user_mute(
    callback_query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    callback_data: ToggleMuteCallback,
    moderation_service: FromDishka[ModerationService],
    report_service: FromDishka[ReportService],
    uow: Annotated[IUnitOfWork, FromDishka()],
    user_settings_service: FromDishka[UserSettingsService],
) -> None:
    """Handles the action of toggling the mute status for a specific user."""
    async with uow:
        toggle_result = await moderation_service.toggle_mute_from_paginated_list(
            uow,
            telegram_id=callback_query.from_user.id,
            list_type=callback_data.list_type,
            page=callback_data.current_page,
            index_on_page=callback_data.user_idx,
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

    _ = translator.gettext

    if toggle_result.success and toggle_result.user_settings:
        # Fetch the updated mute list display data

        async with uow:
            mute_list_display_data = (
                await user_settings_service.get_mute_list_display_data(
                    uow,
                    callback_query.from_user.id,
                    translator.info().get("language", "en"),  # Use current language
                    cast("EventBot", callback_query.bot),
                )
            )
        if not mute_list_display_data:
            logger.warning(
                "Could not retrieve mute list display data for user %s after toggle.",
                callback_query.from_user.id,
            )
            await callback_query.answer(
                _("An error occurred. Please try again later."), show_alert=True
            )
            return

        await _refresh_mute_related_ui(
            callback_query,
            translator,
            mute_list_display_data,
            report_service,
            moderation_service,
            callback_data,
        )
