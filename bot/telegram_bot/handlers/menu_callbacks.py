import logging
import gettext # Added for type hinting
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from pytalk.instance import TeamTalkInstance

from bot.telegram_bot.callback_data import MenuCallback
from bot.telegram_bot.handlers.user import who_command_handler, help_command_handler, settings_command_handler
from bot.telegram_bot.handlers.admin import kick_command_handler, ban_command_handler, subscribers_command_handler
from bot.models import UserSettings

logger = logging.getLogger(__name__)
menu_callback_router = Router(name="menu_callback_router")

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "who"))
async def menu_who_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    tt_instance: TeamTalkInstance | None,
    translator: "gettext.GNUTranslations"  # Changed from _: callable
):
    """Handles the 'Who is online?' menu button."""
    if not query.message:
        logger.error("menu_who_handler: query.message is None.")
        # Use translator.gettext for direct calls if needed before full context
        await query.answer(translator.gettext("Error processing command."), show_alert=True)
        return
    # who_command_handler expects the full translator object
    await who_command_handler(message=query.message, tt_instance=tt_instance, translator=translator)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "help"))
async def menu_help_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations"  # Changed from _: callable
):
    """Handles the 'Help' menu button."""
    if not query.message:
        logger.error("menu_help_handler: query.message is None.")
        await query.answer(translator.gettext("Error processing command."), show_alert=True)
        return
    # help_command_handler expects _, which is translator.gettext
    await help_command_handler(message=query.message, _=translator.gettext)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "settings"))
async def menu_settings_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations"  # Changed from _: callable
):
    """Handles the 'Settings' menu button."""
    if not query.message:
        logger.error("menu_settings_handler: query.message is None.")
        await query.answer(translator.gettext("Error processing command."), show_alert=True)
        return
    # settings_command_handler expects _, which is translator.gettext
    await settings_command_handler(message=query.message, _=translator.gettext)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
async def menu_kick_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",  # Changed from _: callable
    tt_instance: TeamTalkInstance | None
):
    """Handles the 'Kick User' menu button."""
    if not query.message:
        logger.error("menu_kick_handler: query.message is None.")
        await query.answer(translator.gettext("Error processing command."), show_alert=True)
        return
    # kick_command_handler expects _, which is translator.gettext
    await kick_command_handler(message=query.message, _=translator.gettext, tt_instance=tt_instance)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
async def menu_ban_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    translator: "gettext.GNUTranslations",  # Changed from _: callable
    tt_instance: TeamTalkInstance | None
):
    """Handles the 'Ban User' menu button."""
    if not query.message:
        logger.error("menu_ban_handler: query.message is None.")
        await query.answer(translator.gettext("Error processing command."), show_alert=True)
        return
    # ban_command_handler expects _, which is translator.gettext
    await ban_command_handler(message=query.message, _=translator.gettext, tt_instance=tt_instance)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "subscribers"))
async def menu_subscribers_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    session: AsyncSession,
    bot: Bot,
    translator: "gettext.GNUTranslations"  # Changed from _: callable
):
    """Handles the 'Subscribers' menu button."""
    if not query.message:
        logger.error("menu_subscribers_handler: query.message is None.")
        await query.answer(translator.gettext("Error processing command."), show_alert=True)
        return
    # subscribers_command_handler expects _, which is translator.gettext
    await subscribers_command_handler(message=query.message, session=session, bot=bot, _=translator.gettext)
    await query.answer()
