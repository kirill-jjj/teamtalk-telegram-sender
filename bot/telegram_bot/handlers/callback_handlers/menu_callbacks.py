"""Callback query handlers for main menu button interactions."""

from gettext import NullTranslations
import logging
from typing import cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import AdminCommand
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.report_service import ReportService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import MenuCallback
from bot.telegram_bot.handlers.admin import _show_user_buttons
from bot.telegram_bot.handlers.user import (
    on_help_command,
    on_settings_command,
    on_who_command,
)
from bot.telegram_bot.types.bots import EventBot

from ._helpers import ensure_message_context
from .list_utils import (
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
    translator: FromDishka[NullTranslations],
    cache: FromDishka[CacheService],
    tt_connection: TeamTalkConnection,
    bot: FromDishka[EventBot],
    report_service: FromDishka[ReportService],
) -> None:
    """Handles the 'Who is online?' menu button click."""
    await on_who_command(
        message=query.message,
        translator=translator,
        cache=cache,
        tt_connection=tt_connection,
        bot=bot,
        report_service=report_service,
    )


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


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
@ensure_message_context
async def menu_kick_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    tt_connection: TeamTalkConnection,
) -> None:
    """Handles the 'Kick User' admin menu button click."""
    if isinstance(query.message, Message):
        await _show_user_buttons(
            query.message, AdminCommand.KICK, translator, tt_connection
        )


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
@ensure_message_context
async def menu_ban_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    tt_connection: TeamTalkConnection,
) -> None:
    """Handles the 'Ban User' admin menu button click."""
    if isinstance(query.message, Message):
        await _show_user_buttons(
            query.message, AdminCommand.BAN, translator, tt_connection
        )


@admin_menu_callback_router.callback_query(
    MenuCallback.filter(F.command == "subscribers")
)
@ensure_message_context
async def menu_subscribers_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles the 'Subscribers' admin menu button click."""
    async with uow:
        await _show_subscriber_list_page(
            cast(Message, query.message),
            uow.users,
            uow.subscribers,
            bot,
            translator,
            page=0,
        )


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "unban"))
@ensure_message_context
async def menu_unban_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    uow: FromDishka[IUnitOfWork],
) -> None:
    """Handles the 'Unban User' admin menu button click."""
    async with uow:
        await _show_banned_list_page(
            target=cast(Message, query.message),
            ban_repo=uow.bans,
            bot=bot,
            page=0,
            translator=translator,
        )
