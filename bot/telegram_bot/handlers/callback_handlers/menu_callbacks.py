"""Callback query handlers for main menu button interactions."""

from gettext import NullTranslations
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from dishka.integrations.aiogram import FromDishka
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import AdminCommand
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import MenuCallback

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
) -> None:
    """Handles the 'Who is online?' menu button click."""
    await on_who_command(
        message=query.message,
        translator=translator,
        cache=cache,
        tt_connection=tt_connection,
        bot=query.bot,
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
    session: FromDishka[AsyncSession],
    translator: FromDishka[NullTranslations],
    bot: FromDishka[Bot],
) -> None:
    """Handles the 'Subscribers' admin menu button click."""
    await _show_subscriber_list_page(query.message, session, bot, translator, page=0)  # type: ignore[arg-type]
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "unban"))
@ensure_message_context
async def menu_unban_handler(
    query: CallbackQuery,
    session: FromDishka[AsyncSession],
    translator: FromDishka[NullTranslations],
    bot: FromDishka[Bot],
) -> None:
    """Handles the 'Unban User' admin menu button click."""
    await _show_banned_list_page(
        target=query.message,  # type: ignore[arg-type]
        session=session,
        bot=bot,
        page=0,
        translator=translator,
    )
    await query.answer()
