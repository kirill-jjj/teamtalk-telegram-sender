import logging
import gettext
from aiogram import Router, F, Bot as AiogramBot # Renamed Bot
from aiogram.types import CallbackQuery # Message removed as ensure_message_context provides it
# from aiogram.fsm.context import FSMContext # Not used
from sqlalchemy.ext.asyncio import AsyncSession
# from pytalk.instance import TeamTalkInstance # Will use tt_connection from data
from bot.teamtalk_bot.connection import TeamTalkConnection # For type hinting

from bot.telegram_bot.callback_data import MenuCallback
from bot.telegram_bot.handlers.user import who_command_handler, help_command_handler, settings_command_handler
from bot.telegram_bot.handlers.admin import kick_command_handler, ban_command_handler, subscribers_command_handler
# from bot.models import UserSettings # Not directly used as param, user_settings comes from middleware for command handlers
from bot.telegram_bot.handlers.callback_handlers._helpers import ensure_message_context

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)
menu_callback_router = Router(name="menu_callback_router")
# TeamTalkConnectionCheckMiddleware is assumed to be applied globally or on a parent router
# for handlers like 'who', 'kick', 'ban' that require tt_connection.

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "who"))
@ensure_message_context
async def menu_who_handler(
    query: CallbackQuery, # Message object is injected by @ensure_message_context
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations", # Provided by UserSettingsMiddleware
    app: "Application", # Provided by ApplicationMiddleware
    tt_connection: TeamTalkConnection | None # Provided by ActiveTeamTalkConnectionMiddleware
):
    # who_command_handler now expects: message, translator, app, tt_connection
    await who_command_handler(
        message=query.message,
        translator=translator,
        app=app,
        tt_connection=tt_connection
    )
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "help"))
@ensure_message_context
async def menu_help_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application" # help_command_handler now needs app
):
    # help_command_handler now expects: message, _, app
    await help_command_handler(
        message=query.message,
        _=translator.gettext,
        app=app
    )
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "settings"))
@ensure_message_context
async def menu_settings_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application" # settings_command_handler now needs app
):
    # settings_command_handler now expects: message, _, app
    await settings_command_handler(
        message=query.message,
        _=translator.gettext,
        app=app
    )
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
@ensure_message_context
async def menu_kick_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application", # kick_command_handler now needs app
    tt_connection: TeamTalkConnection | None
):
    # kick_command_handler now expects: message, _, app, tt_connection
    await kick_command_handler(
        message=query.message,
        _=translator.gettext,
        app=app,
        tt_connection=tt_connection
    )
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
@ensure_message_context
async def menu_ban_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application", # ban_command_handler now needs app
    tt_connection: TeamTalkConnection | None
):
    # ban_command_handler now expects: message, _, app, tt_connection
    await ban_command_handler(
        message=query.message,
        _=translator.gettext,
        app=app,
        tt_connection=tt_connection
    )
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "subscribers"))
@ensure_message_context
async def menu_subscribers_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    session: AsyncSession, # Provided by DbSessionMiddleware
    bot: AiogramBot, # Provided by Aiogram
    translator: "gettext.GNUTranslations",
    app: "Application" # subscribers_command_handler now needs app
):
    # subscribers_command_handler now expects: message, session, bot, _, app
    await subscribers_command_handler(
        message=query.message,
        session=session,
        bot=bot,
        _=translator.gettext,
        app=app
    )
    await query.answer()
