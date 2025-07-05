import logging
import gettext
from aiogram import Router, F, Bot as AiogramBot
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from bot.teamtalk_bot.connection import TeamTalkConnection

from bot.telegram_bot.callback_data import MenuCallback
from bot.telegram_bot.handlers.user import who_command_handler, help_command_handler, settings_command_handler
from bot.telegram_bot.handlers.admin import kick_command_handler, ban_command_handler, subscribers_command_handler
from bot.telegram_bot.handlers.callback_handlers._helpers import ensure_message_context

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)
menu_callback_router = Router(name="menu_callback_router")

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "who"))
@ensure_message_context
async def menu_who_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    app: "Application",
    tt_connection: TeamTalkConnection | None
):
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
    app: "Application"
):
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
    app: "Application"
):
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
    app: "Application",
    tt_connection: TeamTalkConnection | None
):
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
    app: "Application",
    tt_connection: TeamTalkConnection | None
):
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
    session: AsyncSession,
    bot: AiogramBot,
    translator: "gettext.GNUTranslations",
    app: "Application"
):
    await subscribers_command_handler(
        message=query.message,
        session=session,
        bot=bot,
        _=translator.gettext,
        app=app
    )
    await query.answer()
