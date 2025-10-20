"""Callback query handlers for main menu button interactions."""

from gettext import NullTranslations
import logging
from typing import Annotated, cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.config import Settings
from bot.core.enums import AdminCommand
from bot.services.cache_service import CacheService
from bot.services.report_service import ReportService
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import MenuCallback
from bot.telegram_bot.formatters import format_who_report_to_html
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.handlers.user import (
    on_help_command,
    on_settings_command,
)
from bot.telegram_bot.keyboards import (
    create_banned_user_list_keyboard,
    create_subscriber_list_keyboard,
)
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import display_moderation_view, display_paginated_list

logger = logging.getLogger(__name__)
menu_callback_router = Router(name="menu_callback_router")
admin_menu_callback_router = Router(name="admin_menu_callback_router")


@menu_callback_router.callback_query(MenuCallback.filter(F.command == "who"))
@ensure_message_context
async def menu_who_handler(
    query: CallbackQuery,
    translator: Annotated[NullTranslations, FromDishka()],
    cache: Annotated[CacheService, FromDishka()],
    bot: Annotated[EventBot, FromDishka()],
    command_bus: Annotated[CommandBus, FromDishka()],
    user_settings_service: Annotated[UserSettingsService, FromDishka()],
    settings: Annotated[Settings, FromDishka()],
    report_service: Annotated[ReportService, FromDishka()],
) -> None:
    """Handles the 'Who is online?' menu button click."""
    if not query.from_user:
        return

    report_dto = await report_service.get_who_report_data(
        telegram_user_id=query.from_user.id,
        translator=translator,
        cache_service=cache,
        user_settings_service=user_settings_service,
        command_bus=command_bus,
    )

    report_text = format_who_report_to_html(report_dto, translator)

    if query.message:
        await query.message.reply(report_text)
    await query.answer()


@menu_callback_router.callback_query(MenuCallback.filter(F.command == "help"))
@ensure_message_context
async def menu_help_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    cache: FromDishka[CacheService],
) -> None:
    """Handles the 'Help' menu button click."""
    await on_help_command(
        message=query.message,
        translator=translator,
        cache=cache,
    )
    await query.answer()


@menu_callback_router.callback_query(MenuCallback.filter(F.command == "settings"))
@ensure_message_context
async def menu_settings_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
) -> None:
    """Handles the 'Settings' menu button click."""
    await on_settings_command(
        message=query.message,
        translator=translator,
    )
    await query.answer()


async def _handle_menu_moderation_command(
    query: CallbackQuery,
    command_type: AdminCommand,
    translator: NullTranslations,
    report_service: ReportService,
    cache_service: CacheService,
    user_settings_service: UserSettingsService,
    command_bus: CommandBus,
) -> None:
    """Generic handler for menu-based moderation commands."""
    if not query.from_user or not isinstance(query.message, Message):
        return

    view_data = await report_service.get_sorted_online_users_for_moderation(
        telegram_user_id=query.from_user.id,
        translator=translator,
        cache_service=cache_service,
        user_settings_service=user_settings_service,
        command_bus=command_bus,
    )

    await display_moderation_view(
        message=query.message,
        translator=translator,
        command_type=command_type,
        view_data=view_data,
    )
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
@ensure_message_context
async def menu_kick_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    report_service: FromDishka[ReportService],
    cache_service: FromDishka[CacheService],
    user_settings_service: FromDishka[UserSettingsService],
    command_bus: FromDishka[CommandBus],
) -> None:
    """Handles the 'Kick User' admin menu button click."""
    await _handle_menu_moderation_command(
        query,
        AdminCommand.KICK,
        translator,
        report_service,
        cache_service,
        user_settings_service,
        command_bus,
    )


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
@ensure_message_context
async def menu_ban_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    report_service: FromDishka[ReportService],
    cache_service: FromDishka[CacheService],
    user_settings_service: FromDishka[UserSettingsService],
    command_bus: FromDishka[CommandBus],
) -> None:
    """Handles the 'Ban User' admin menu button click."""
    await _handle_menu_moderation_command(
        query,
        AdminCommand.BAN,
        translator,
        report_service,
        cache_service,
        user_settings_service,
        command_bus,
    )


@admin_menu_callback_router.callback_query(
    MenuCallback.filter(F.command == "subscribers")
)
@ensure_message_context
async def menu_subscribers_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    report_service: FromDishka[ReportService],
) -> None:
    """Handles the 'Subscribers' admin menu button click."""
    _ = translator.gettext

    result = await report_service.get_subscribers_info(page=0)

    await display_paginated_list(
        target=cast(Message, query.message),
        bot=bot,
        translator=translator,
        items_on_page=result.items,
        total_items=result.total_items,
        page=result.current_page,
        title_text=_("Here is the list of subscribers."),
        empty_list_text=_("No subscribers found."),
        keyboard_factory=create_subscriber_list_keyboard,
        keyboard_factory_kwargs={},
    )
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "unban"))
@ensure_message_context
async def menu_unban_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    report_service: FromDishka[ReportService],
) -> None:
    """Handles the 'Unban User' admin menu button click."""
    _ = translator.gettext

    result = await report_service.get_banned_users_info(page=0)

    await display_paginated_list(
        target=cast(Message, query.message),
        bot=bot,
        translator=translator,
        items_on_page=result.items,
        total_items=result.total_items,
        page=result.current_page,
        title_text=_("Banned Users"),
        empty_list_text=_("The ban list is empty."),
        keyboard_factory=create_banned_user_list_keyboard,
        keyboard_factory_kwargs={},
    )
    await query.answer()
