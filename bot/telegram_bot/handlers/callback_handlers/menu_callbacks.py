"""Callback query handlers for main menu button interactions."""

from gettext import NullTranslations
import logging
from typing import cast

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka

from bot.core.enums import AdminCommand
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import MenuCallback
from bot.telegram_bot.types.bots import EventBot

from ..admin import _show_user_buttons
from ..user import on_help_command, on_settings_command, on_who_command
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
) -> None:
    """Handles the 'Who is online?' menu button click."""
    await on_who_command(
        message=query.message,
        translator=translator,
        cache=cache,
        tt_connection=tt_connection,
        bot=bot,
    )
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


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
@ensure_message_context
async def menu_kick_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    tt_connection: TeamTalkConnection,
) -> None:
    """Handles the 'Kick User' admin menu button click."""
    await _show_user_buttons(query.message, AdminCommand.KICK, translator, tt_connection)  # type: ignore[arg-type]
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
@ensure_message_context
async def menu_ban_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    tt_connection: TeamTalkConnection,
) -> None:
    """Handles the 'Ban User' admin menu button click."""
    await _show_user_buttons(query.message, AdminCommand.BAN, translator, tt_connection)  # type: ignore[arg-type]
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "subscribers"))
@ensure_message_context
async def menu_subscribers_handler(
    query: CallbackQuery,
    translator: FromDishka[NullTranslations],
    bot: FromDishka[EventBot],
    user_repo: FromDishka[UserRepository],
    subscriber_repo: FromDishka[SubscriberRepository],
) -> None:
    """Handles the 'Subscribers' admin menu button click."""
    await _show_subscriber_list_page(
        cast(Message, query.message),
        user_repo,
        subscriber_repo,
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
    ban_repo: FromDishka[BanRepository],
) -> None:
    """Handles the 'Unban User' admin menu button click."""
    await _show_banned_list_page(
        target=cast(Message, query.message),
        ban_repo=ban_repo,
        bot=bot,
        page=0,
        translator=translator,
    )
    await query.answer()
