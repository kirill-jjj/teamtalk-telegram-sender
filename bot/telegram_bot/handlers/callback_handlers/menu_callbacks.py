import logging
import gettext
from aiogram import Router, F, Bot as AiogramBot
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from bot.teamtalk_bot.connection import TeamTalkConnection

# Импортируем бизнес-логику напрямую, а не через хендлеры
from ..admin import _show_user_buttons
from .list_utils import _show_subscriber_list_page
from ..user import who_command_handler, help_command_handler, settings_command_handler
from ._helpers import ensure_message_context
from ...middlewares.admin_check import AdminCheckMiddleware
# Middlewares to apply
from ...middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware

from bot.telegram_bot.callback_data import MenuCallback
from bot.core.enums import AdminAction

# Для типизации
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)
menu_callback_router = Router(name="menu_callback_router")
# Apply TT middlewares to menu_callback_router for 'who' command
menu_callback_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None)) # Added
menu_callback_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware()) # Added

admin_menu_callback_router = Router(name="admin_menu_callback_router")
admin_menu_callback_router.callback_query.middleware(AdminCheckMiddleware())
# Apply TT middlewares to admin_menu_callback_router for 'kick', 'ban' commands
admin_menu_callback_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None)) # Added
admin_menu_callback_router.callback_query.middleware(TeamTalkConnectionCheckMiddleware()) # Added


# --- Хендлеры обычных пользователей ---

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "who"))
@ensure_message_context
async def menu_who_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations", # Injected by UserSettingsMiddleware
    admin_ids_cache: Set[int], # Injected from workflow_data
    tt_connection: TeamTalkConnection | None # Injected by ActiveTeamTalkConnectionMiddleware
):
    # Ensure query.message exists due to @ensure_message_context
    await who_command_handler(
        message=query.message, # type: ignore
        translator=translator,
        admin_ids_cache=admin_ids_cache, # Pass admin_ids_cache
        tt_connection=tt_connection
    )
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "help"))
@ensure_message_context
async def menu_help_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations", # Injected by UserSettingsMiddleware
    admin_ids_cache: Set[int] # Injected from workflow_data
):
    # Ensure query.message exists
    await help_command_handler(
        message=query.message, # type: ignore
        _=translator.gettext,
        admin_ids_cache=admin_ids_cache # Pass admin_ids_cache
    )
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "settings"))
@ensure_message_context
async def menu_settings_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations" # Injected by UserSettingsMiddleware
    # app: "Application" removed
):
    # Ensure query.message exists
    await settings_command_handler(
        message=query.message, # type: ignore
        _=translator.gettext
        # app argument removed from settings_command_handler
    )
    await query.answer()


# --- Хендлеры администратора ---

@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
@ensure_message_context
async def menu_kick_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations", # Injected
    # app: "Application", # Removed
    tt_connection: TeamTalkConnection | None # Injected
):
    # Ensure query.message exists
    await _show_user_buttons(query.message, AdminAction.KICK, translator.gettext, tt_connection) # type: ignore
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
@ensure_message_context
async def menu_ban_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations", # Injected
    # app: "Application", # Removed
    tt_connection: TeamTalkConnection | None # Injected
):
    # Ensure query.message exists
    await _show_user_buttons(query.message, AdminAction.BAN, translator.gettext, tt_connection) # type: ignore
    await query.answer()


@admin_menu_callback_router.callback_query(MenuCallback.filter(F.command == "subscribers"))
@ensure_message_context
async def menu_subscribers_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    session: AsyncSession, # Injected
    bot: AiogramBot, # Injected
    translator: "gettext.GNUTranslations" # Injected
    # app: "Application" # Removed
):
    # Ensure query.message exists
    await _show_subscriber_list_page(query.message, session, bot, translator.gettext, page=0) # type: ignore
    await query.answer()
