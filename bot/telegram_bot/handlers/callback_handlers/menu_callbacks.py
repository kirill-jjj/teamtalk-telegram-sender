"""Callback query handlers for main menu button interactions."""

from gettext import NullTranslations
import logging
from typing import Annotated, cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka

from bot.command_bus.bus import CommandBus
from bot.command_bus.exceptions import NoHandlerFoundError
from bot.commands import GetOnlineUsersCommand, GetOnlineUsersResult
from bot.config import Settings
from bot.core.enums import AdminCommand
from bot.services.cache_service import CacheService
from bot.services.report_service import ReportService
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.callback_data import MenuCallback
from bot.telegram_bot.formatters import format_who_report_to_html
from bot.telegram_bot.handlers.admin import show_user_buttons_from_list
from bot.telegram_bot.handlers.decorators import ensure_message_context
from bot.telegram_bot.handlers.user import (
    on_help_command,
    on_settings_command,
)
from bot.telegram_bot.types.bots import EventBot
from bot.telegram_bot.ui_utils import (
    _show_banned_list_page,
    _show_subscriber_list_page,
)

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
    _ = translator.gettext
    if not query.from_user:
        return

    report_data = await report_service.get_who_report_data(
        telegram_user_id=query.from_user.id,
        translator=translator,
        cache_service=cache,
        user_settings_service=user_settings_service,
        command_bus=command_bus,
    )

    if isinstance(report_data, str):
        report_text = report_data
    else:
        report_text = format_who_report_to_html(report_data, translator)

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
    command_bus: CommandBus,
    settings: Settings,
) -> None:
    """Generic handler for menu-based moderation commands."""
    _ = translator.gettext
    if isinstance(query.message, Message):
        try:
            result: GetOnlineUsersResult = await command_bus.execute(
                GetOnlineUsersCommand(
                    is_caller_admin=True,
                    lang_code=translator.info().get("language", "en"),
                )
            )
        except NoHandlerFoundError:
            logger.critical("CRITICAL: No handler for GetOnlineUsersCommand!")
            await query.message.reply(_("This feature is temporarily unavailable."))
            await query.answer()
            return

        if result.success and result.users:
            await show_user_buttons_from_list(
                query.message,
                command_type,
                translator,
                result.users,
                settings.teamtalk.host_name,
            )
        else:
            await query.message.reply(
                result.error_message or _("Failed to get user list.")
            )
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
@ensure_message_context
async def menu_kick_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    command_bus: FromDishka[CommandBus],
    settings: FromDishka[Settings],
) -> None:
    """Handles the 'Kick User' admin menu button click."""
    await _handle_menu_moderation_command(
        query, AdminCommand.KICK, translator, command_bus, settings
    )


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
@ensure_message_context
async def menu_ban_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    command_bus: FromDishka[CommandBus],
    settings: FromDishka[Settings],
) -> None:
    """Handles the 'Ban User' admin menu button click."""
    await _handle_menu_moderation_command(
        query, AdminCommand.BAN, translator, command_bus, settings
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
    await _show_subscriber_list_page(
        cast("Message", query.message),
        report_service,
        bot,
        translator,
        page=0,
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
    await _show_banned_list_page(
        target=cast("Message", query.message),
        report_service=report_service,
        bot=bot,
        translator=translator,
        page=0,
    )
    await query.answer()
