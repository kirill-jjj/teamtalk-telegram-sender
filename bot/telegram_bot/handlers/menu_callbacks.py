import logging
import gettext
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from pytalk.instance import TeamTalkInstance

from bot.telegram_bot.callback_data import MenuCallback
from bot.telegram_bot.handlers.user import who_command_handler, help_command_handler, settings_command_handler
from bot.telegram_bot.handlers.admin import kick_command_handler, ban_command_handler, subscribers_command_handler
from bot.models import UserSettings
from bot.telegram_bot.handlers.callback_handlers._helpers import ensure_message_context

logger = logging.getLogger(__name__)
menu_callback_router = Router(name="menu_callback_router")

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "who"))
@ensure_message_context
async def menu_who_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    tt_instance: TeamTalkInstance | None,
    translator: "gettext.GNUTranslations"
):
    """Handles the 'Who is online?' menu button."""
    # The ensure_message_context decorator handles the query.message check.
    # who_command_handler expects the full translator object
    await who_command_handler(message=query.message, tt_instance=tt_instance, translator=translator)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "help"))
@ensure_message_context
async def menu_help_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations"
):
    """Handles the 'Help' menu button."""
    # The ensure_message_context decorator handles the query.message check.
    # help_command_handler expects _, which is translator.gettext
    await help_command_handler(message=query.message, _=translator.gettext)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "settings"))
@ensure_message_context
async def menu_settings_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations"
):
    """Handles the 'Settings' menu button."""
    # The ensure_message_context decorator handles the query.message check.
    # settings_command_handler expects _, which is translator.gettext
    await settings_command_handler(message=query.message, _=translator.gettext)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
@ensure_message_context
async def menu_kick_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    tt_instance: TeamTalkInstance | None
):
    """Handles the 'Kick User' menu button."""
    # The ensure_message_context decorator handles the query.message check.
    # kick_command_handler expects _, which is translator.gettext
    await kick_command_handler(message=query.message, _=translator.gettext, tt_instance=tt_instance)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
@ensure_message_context
async def menu_ban_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",
    tt_instance: TeamTalkInstance | None
):
    """Handles the 'Ban User' menu button."""
    # The ensure_message_context decorator handles the query.message check.
    # ban_command_handler expects _, which is translator.gettext
    await ban_command_handler(message=query.message, _=translator.gettext, tt_instance=tt_instance)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "subscribers"))
@ensure_message_context
async def menu_subscribers_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    session: AsyncSession,
    bot: Bot,
    translator: "gettext.GNUTranslations"
):
    """Handles the 'Subscribers' menu button."""
    # The ensure_message_context decorator handles the query.message check.
    # subscribers_command_handler expects _, which is translator.gettext
    await subscribers_command_handler(message=query.message, session=session, bot=bot, _=translator.gettext)
    await query.answer()
