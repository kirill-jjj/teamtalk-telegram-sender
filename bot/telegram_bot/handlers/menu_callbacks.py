import logging
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
    _: callable
):
    """Handles the 'Who is online?' menu button."""
    if not query.message:
        logger.error("menu_who_handler: query.message is None.")
        await query.answer(_("Error processing command."), show_alert=True)
        return
    await who_command_handler(message=query.message, tt_instance=tt_instance, translator=_)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "help"))
async def menu_help_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    _: callable
):
    """Handles the 'Help' menu button."""
    if not query.message:
        logger.error("menu_help_handler: query.message is None.")
        await query.answer(_("Error processing command."), show_alert=True)
        return
    await help_command_handler(message=query.message, _=_)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "settings"))
async def menu_settings_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    _: callable
):
    """Handles the 'Settings' menu button."""
    if not query.message:
        logger.error("menu_settings_handler: query.message is None.")
        await query.answer(_("Error processing command."), show_alert=True)
        return
    await settings_command_handler(message=query.message, _=_)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "kick"))
async def menu_kick_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    _: callable,
    tt_instance: TeamTalkInstance | None
):
    """Handles the 'Kick User' menu button."""
    if not query.message:
        logger.error("menu_kick_handler: query.message is None.")
        await query.answer(_("Error processing command."), show_alert=True)
        return
    await kick_command_handler(message=query.message, _=_, tt_instance=tt_instance)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "ban"))
async def menu_ban_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    _: callable,
    tt_instance: TeamTalkInstance | None
):
    """Handles the 'Ban User' menu button."""
    if not query.message:
        logger.error("menu_ban_handler: query.message is None.")
        await query.answer(_("Error processing command."), show_alert=True)
        return
    await ban_command_handler(message=query.message, _=_, tt_instance=tt_instance)
    await query.answer()

@menu_callback_router.callback_query(MenuCallback.filter(F.command == "subscribers"))
async def menu_subscribers_handler(
    query: CallbackQuery,
    callback_data: MenuCallback,
    session: AsyncSession,
    bot: Bot,
    _: callable
):
    """Handles the 'Subscribers' menu button."""
    if not query.message:
        logger.error("menu_subscribers_handler: query.message is None.")
        await query.answer(_("Error processing command."), show_alert=True)
        return
    await subscribers_command_handler(message=query.message, session=session, bot=bot, _=_)
    await query.answer()
