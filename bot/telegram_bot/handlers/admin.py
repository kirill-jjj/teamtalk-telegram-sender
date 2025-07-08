"""Telegram bot command handlers for administrator actions."""

import gettext
import logging

from aiogram import Bot as AiogramBot
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.enums import AdminAction
from bot.core.utils import get_online_teamtalk_users, get_tt_user_display_name
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.keyboards import create_user_selection_keyboard

from .callback_handlers.list_utils import _show_subscriber_list_page

logger = logging.getLogger(__name__)

admin_router = Router(name="admin_router")


async def _show_user_buttons(
    message: Message,
    command_type: AdminAction,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
):
    _ = translator.gettext
    if not tt_connection or not tt_connection.instance:
        # This case should ideally be caught by TeamTalkConnectionCheckMiddleware
        logger.error(
            "tt_connection or its instance is None in _show_user_buttons. This should have been caught by middleware."
        )
        await message.reply(_("TeamTalk connection is not available. Please try again later."))
        return

    tt_instance = tt_connection.instance

    my_user_id = tt_instance.getMyUserID()
    if my_user_id is None:
        logger.error("[%s] Could not get own user ID in _show_user_buttons.", tt_connection.server_info.host)
        await message.reply(_("An error occurred. Please try again later."))
        return

    online_users = await get_online_teamtalk_users(tt_instance)

    if not online_users:
        await message.reply(
            _("No users found online on server {server_host}.").format(server_host=tt_connection.server_info.host)
        )
        return

    sorted_users = sorted(online_users, key=lambda u: get_tt_user_display_name(u, translator).lower())
    builder = await create_user_selection_keyboard(translator, sorted_users, command_type)

    command_text_map = {
        AdminAction.KICK: _("Select a user to kick from {server_host}:").format(
            server_host=tt_connection.server_info.host
        ),
        AdminAction.BAN: _("Select a user to ban from {server_host}:").format(
            server_host=tt_connection.server_info.host
        ),
    }
    reply_text = command_text_map.get(command_type, _("Select a user:"))

    await message.reply(reply_text, reply_markup=builder.as_markup())


@admin_router.message(Command("kick"))
async def kick_command_handler(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
):
    """Handles the /kick command for administrators."""
    await _show_user_buttons(message, AdminAction.KICK, translator, tt_connection)


@admin_router.message(Command("ban"))
async def ban_command_handler(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
):
    """Handles the /ban command for administrators."""
    await _show_user_buttons(message, AdminAction.BAN, translator, tt_connection)


@admin_router.message(Command("subscribers"))
async def subscribers_command_handler(
    message: Message,
    session: AsyncSession,  # Injected by DbSessionMiddleware
    bot: AiogramBot,  # Injected by Aiogram (Dispatcher has it)
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
):
    """Handles the /subscribers command for administrators."""
    await _show_subscriber_list_page(message, session, bot, translator, page=0)
