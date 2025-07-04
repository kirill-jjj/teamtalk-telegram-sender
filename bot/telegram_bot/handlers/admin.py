import logging
from aiogram import Router, Bot as AiogramBot, F # Renamed Bot
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

# from bot.state import ADMIN_IDS_CACHE # Will use app.admin_ids_cache
from bot.core.utils import get_tt_user_display_name, get_online_teamtalk_users
from bot.telegram_bot.keyboards import create_user_selection_keyboard # create_subscriber_list_keyboard moved
# from bot.telegram_bot.utils import send_or_edit_paginated_list # Not used directly here
from bot.telegram_bot.middlewares import TeamTalkConnectionCheckMiddleware # Use the correct check middleware
from bot.teamtalk_bot.connection import TeamTalkConnection # For type hinting

from bot.core.enums import AdminAction
# from pytalk.instance import TeamTalkInstance # Will use tt_connection.instance
from .callback_handlers.list_utils import _show_subscriber_list_page

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)

admin_router = Router(name="admin_router")
# Apply middleware to message handlers on this router that need TT connection check
admin_router.message.middleware(TeamTalkConnectionCheckMiddleware())


async def _show_user_buttons(
    message: Message,
    command_type: AdminAction,
    _: callable,
    tt_connection: TeamTalkConnection | None
):
    if not tt_connection or not tt_connection.instance:
        logger.error("tt_connection or its instance is None in _show_user_buttons.")
        # Middleware should prevent this, but defensive check.
        await message.reply(_("TeamTalk connection is not available."))
        return

    tt_instance = tt_connection.instance # Use the instance from the connection

    my_user_id = tt_instance.getMyUserID()
    if my_user_id is None:
        logger.error(f"[{tt_connection.server_info.host}] Could not get own user ID in _show_user_buttons.")
        await message.reply(_("An error occurred determining your TeamTalk ID."))
        return

    # online_users now comes from the connection's cache, or fetched via its instance
    # get_online_teamtalk_users helper needs to be adapted or use cache directly.
    # For now, assume get_online_teamtalk_users takes tt_instance.
    online_users = await get_online_teamtalk_users(tt_instance) # This helper might need update if it used global cache

    if not online_users:
        await message.reply(_("No users online on TeamTalk server {server_host}.").format(server_host=tt_connection.server_info.host))
        return

    sorted_users = sorted(online_users, key=lambda u: get_tt_user_display_name(u, _).lower())
    builder = create_user_selection_keyboard(_, sorted_users, command_type)

    command_text_map = {
        AdminAction.KICK: _("Select a user to kick from {server_host}:").format(server_host=tt_connection.server_info.host),
        AdminAction.BAN: _("Select a user to ban from {server_host}:").format(server_host=tt_connection.server_info.host)
    }
    reply_text = command_text_map.get(command_type, _("Select a user:"))

    await message.reply(reply_text, reply_markup=builder.as_markup())


# The F.from_user.id.in_(ADMIN_IDS_CACHE) filter needs to be replaced or adapted.
# For now, we'll check within the handler using app.admin_ids_cache.
# A custom filter would be cleaner eventually.

@admin_router.message(Command("kick")) # Removed F.from_user.id.in_(ADMIN_IDS_CACHE)
async def kick_command_handler(
    message: Message,
    _: callable,
    app: "Application", # Get app instance from middleware
    tt_connection: TeamTalkConnection | None # Get connection from middleware
):
    if message.from_user.id not in app.admin_ids_cache:
        await message.reply(_("You are not authorized to use this command."))
        return
    # tt_connection is now guaranteed by TeamTalkConnectionCheckMiddleware to be ready
    await _show_user_buttons(message, AdminAction.KICK, _, tt_connection)


@admin_router.message(Command("ban")) # Removed F.from_user.id.in_(ADMIN_IDS_CACHE)
async def ban_command_handler(
    message: Message,
    _: callable,
    app: "Application", # Get app instance
    tt_connection: TeamTalkConnection | None # Get connection
):
    if message.from_user.id not in app.admin_ids_cache:
        await message.reply(_("You are not authorized to use this command."))
        return
    await _show_user_buttons(message, AdminAction.BAN, _, tt_connection)


@admin_router.message(Command("subscribers")) # Removed F.from_user.id.in_(ADMIN_IDS_CACHE)
async def subscribers_command_handler(
    message: Message,
    session: AsyncSession,
    bot: AiogramBot, # This is the Aiogram Bot instance
    _: callable,
    app: "Application" # Get app instance
):
    if message.from_user.id not in app.admin_ids_cache:
        await message.reply(_("You are not authorized to use this command."))
        return
    # _show_subscriber_list_page probably uses crud and session, not directly app or tt_connection
    # It might need `app.tg_bot_event` if it sends messages. The `bot` param here is fine.
    await _show_subscriber_list_page(message, session, bot, _, page=0)
