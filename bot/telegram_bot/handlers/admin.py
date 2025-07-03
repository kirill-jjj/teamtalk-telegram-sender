import logging
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.state import ADMIN_IDS_CACHE
from bot.core.utils import get_tt_user_display_name, get_online_teamtalk_users
from bot.telegram_bot.keyboards import create_user_selection_keyboard, create_subscriber_list_keyboard
from bot.telegram_bot.utils import send_or_edit_paginated_list
from bot.telegram_bot.middlewares import TeamTalkConnectionMiddleware # Import the middleware

from bot.core.enums import AdminAction
from pytalk.instance import TeamTalkInstance
# Removed: from .callback_handlers.subscriber_list import _get_paginated_subscribers_info
# Added:
from .callback_handlers.list_utils import _get_paginated_subscribers_info, _show_subscriber_list_page

logger = logging.getLogger(__name__)

admin_router = Router(name="admin_router")
# Apply middleware to message handlers on this router that need TT connection
admin_router.message.middleware(TeamTalkConnectionMiddleware())


async def _show_user_buttons(
    message: Message,
    command_type: AdminAction,
    _: callable,
    tt_instance: TeamTalkInstance | None # tt_instance is now guaranteed to be connected by middleware
):
    # Middleware now handles the tt_instance connection check.
    # We can assert tt_instance is not None if needed for type checkers,
    # or trust the middleware has done its job.
    if not tt_instance: # Should not happen if middleware is effective
        logger.error("tt_instance is None in _show_user_buttons despite middleware.")
        await message.reply(_("An unexpected error occurred with TeamTalk connection."))
        return

    my_user_id = tt_instance.getMyUserID()
    if my_user_id is None:
        logger.error("Could not get own user ID in _show_user_buttons.")
        await message.reply(_("An error occurred."))
        return

    my_user_account = tt_instance.get_user(my_user_id)
    if not my_user_account:
        logger.error(f"Could not get own user account object for ID {my_user_id}.")
        await message.reply(_("An error occurred."))
        return

    online_users = await get_online_teamtalk_users(tt_instance)

    if not online_users:
        await message.reply(_("No users online."))
        return

    # get_tt_user_display_name now expects `_` (translator) as its second argument.
    # The `_` here is the admin's translator.
    sorted_users = sorted(online_users, key=lambda u: get_tt_user_display_name(u, _).lower())

    builder = create_user_selection_keyboard(_, sorted_users, command_type)

    command_text_map = {
        AdminAction.KICK: _("Select a user to kick:"),
        AdminAction.BAN: _("Select a user to ban:")
    }
    reply_text = command_text_map.get(command_type, _("Select a user:"))

    await message.reply(reply_text, reply_markup=builder.as_markup())


@admin_router.message(Command("kick"), F.from_user.id.in_(ADMIN_IDS_CACHE))
async def kick_command_handler(
    message: Message,
    _: callable,
    tt_instance: TeamTalkInstance | None
):
    # IsAdminFilter already applied at router level
    await _show_user_buttons(message, AdminAction.KICK, _, tt_instance)


@admin_router.message(Command("ban"), F.from_user.id.in_(ADMIN_IDS_CACHE))
async def ban_command_handler(
    message: Message,
    _: callable,
    tt_instance: TeamTalkInstance | None
):
    # IsAdminFilter already applied at router level
    await _show_user_buttons(message, AdminAction.BAN, _, tt_instance)


@admin_router.message(Command("subscribers"), F.from_user.id.in_(ADMIN_IDS_CACHE))
async def subscribers_command_handler(message: Message, session: AsyncSession, bot: Bot, _: callable):
    """
    Handles the /subscribers command to display a paginated list of subscribed users
    with their names and usernames if available. Admins only.
    """
    await _show_subscriber_list_page(message, session, bot, _, page=0)
