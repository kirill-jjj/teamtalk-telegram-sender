import logging
from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.exceptions import TelegramAPIError

from bot.state import ONLINE_USERS_CACHE, ADMIN_IDS_CACHE
from bot.core.utils import get_username_as_str, get_tt_user_display_name, get_online_teamtalk_users
from bot.telegram_bot.keyboards import create_user_selection_keyboard, create_subscriber_list_keyboard
import pytalk

from bot.core.enums import AdminAction
from pytalk.instance import TeamTalkInstance
from .callback_handlers.subscriber_list import _get_paginated_subscribers_info, SUBSCRIBERS_PER_PAGE

logger = logging.getLogger(__name__)

admin_router = Router(name="admin_router")


async def _show_user_buttons(
    message: Message,
    command_type: AdminAction,
    _: callable,
    tt_instance: TeamTalkInstance | None
):
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await message.reply(_("TeamTalk bot is not connected."))
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
    # Self-filtering by user_id has been removed.

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
    page_subscribers_info, current_page, total_pages = await _get_paginated_subscribers_info(
        session, bot, requested_page=0
    )

    if total_pages == 0 or not page_subscribers_info:
        await message.reply(_("No subscribers found."))
        return

    keyboard = create_subscriber_list_keyboard(
        _,
        page_subscribers_info=page_subscribers_info, # Matching the new parameter name
        current_page=current_page,
        total_pages=total_pages
    )

    await message.reply(
        _("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
            current_page_display=current_page + 1,
            total_pages=total_pages
        ),
        reply_markup=keyboard
    )
