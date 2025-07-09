"""Callback query handlers for main menu button interactions."""

import gettext
import logging
from typing import TYPE_CHECKING

# Removed: from aiogram import Bot as AiogramBot
from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.enums import AdminAction
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import MenuCallback

# Middlewares to apply
from ...middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware
from ...middlewares.admin_check import AdminCheckMiddleware

# Import business logic directly, not through other handlers
from ..admin import _show_user_buttons
from ..user import help_command_handler, settings_command_handler, who_command_handler
from ._helpers import ensure_message_context
from .list_utils import _show_subscriber_list_page

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
menu_callback_router = Router(name="menu_callback_router")
menu_callback_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
menu_callback_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())

admin_menu_callback_router = Router(name="admin_menu_callback_router")
admin_menu_callback_router.callback_query.middleware(AdminCheckMiddleware())
admin_menu_callback_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
admin_menu_callback_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware())


# --- User Handlers ---


@menu_callback_router.callback_query(MenuCallback.filter(F.command == "who"))
@ensure_message_context
async def menu_who_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,  # noqa: ARG001
    translator: "gettext.GNUTranslations",  # Injected by UserSettingsMiddleware
    services: "Services",  # Injected from workflow_data
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
) -> None:
    """Handles the 'Who is online?' menu button click."""
    # Ensure query.message exists due to @ensure_message_context
    # who_command_handler will be refactored to use services.cache.is_admin or accept is_admin
    await who_command_handler(
        message=query.message,
        translator=translator,
        services=services,  # Pass services
        tt_connection=tt_connection,
    )
    await query.answer()


@menu_callback_router.callback_query(MenuCallback.filter(F.command == "help"))
@ensure_message_context
async def menu_help_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,  # noqa: ARG001
    translator: "gettext.GNUTranslations",  # Injected by UserSettingsMiddleware
    services: "Services",  # Injected from workflow_data
) -> None:
    """Handles the 'Help' menu button click."""
    # Ensure query.message exists
    # help_command_handler will be refactored to use services.cache.is_admin or accept is_admin
    await help_command_handler(
        message=query.message,
        translator=translator,
        services=services,  # Pass services
    )
    await query.answer()


@menu_callback_router.callback_query(MenuCallback.filter(F.command == "settings"))
@ensure_message_context
async def menu_settings_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,  # noqa: ARG001
    translator: "gettext.GNUTranslations",  # Injected by UserSettingsMiddleware
) -> None:
    """Handles the 'Settings' menu button click."""
    # Ensure query.message exists
    await settings_command_handler(
        message=query.message,
        translator=translator,
    )
    await query.answer()


# --- Administrator Handlers ---


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
@ensure_message_context
async def menu_kick_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,  # noqa: ARG001
    translator: "gettext.GNUTranslations",  # Injected
    tt_connection: TeamTalkConnection | None,  # Injected
) -> None:
    """Handles the 'Kick User' admin menu button click."""
    # Ensure query.message exists
    await _show_user_buttons(query.message, AdminAction.KICK, translator, tt_connection)  # type: ignore
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
@ensure_message_context
async def menu_ban_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,  # noqa: ARG001
    translator: "gettext.GNUTranslations",  # Injected
    tt_connection: TeamTalkConnection | None,  # Injected
) -> None:
    """Handles the 'Ban User' admin menu button click."""
    # Ensure query.message exists
    await _show_user_buttons(query.message, AdminAction.BAN, translator, tt_connection)  # type: ignore
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "subscribers"))
@ensure_message_context
async def menu_subscribers_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,  # noqa: ARG001
    session: AsyncSession,  # Injected
    translator: "gettext.GNUTranslations",  # Injected
    services: "Services",  # Injected
) -> None:
    """Handles the 'Subscribers' admin menu button click."""
    # Ensure query.message exists
    await _show_subscriber_list_page(query.message, session, services.bot_event, translator, page=0)  # type: ignore
    await query.answer()
