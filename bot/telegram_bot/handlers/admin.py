import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.state import ONLINE_USERS_CACHE
from bot.core.utils import get_username_as_str, get_tt_user_display_name # get_tt_user_display_name now expects `_`
from bot.telegram_bot.keyboards import create_user_selection_keyboard, create_subscriber_list_keyboard
from bot.database.crud import get_all_subscribers_ids
import pytalk # For TeamTalkUser used in _show_user_buttons

from bot.telegram_bot.filters import IsAdminFilter
from pytalk.instance import TeamTalkInstance # For type hint

logger = logging.getLogger(__name__)

SUBSCRIBERS_PER_PAGE = 10
admin_router = Router(name="admin_router")

# Apply the IsAdminFilter to all message and callback_query handlers in this router
admin_router.message.filter(IsAdminFilter())
admin_router.callback_query.filter(IsAdminFilter())


async def _show_user_buttons(
    message: Message,
    command_type: str,
    _: callable,
    tt_instance: TeamTalkInstance | None
):
    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await message.reply(_("TeamTalk bot is not connected.")) # TT_BOT_NOT_CONNECTED
        return

    my_user_id_val = tt_instance.getMyUserID()
    if my_user_id_val is None:
        logger.error("Could not get own user ID in _show_user_buttons.")
        await message.reply(_("An error occurred.")) # error_occurred
        return

    my_user_account = tt_instance.get_user(my_user_id_val)
    if not my_user_account:
        logger.error(f"Could not get own user account object for ID {my_user_id_val}.")
        await message.reply(_("An error occurred.")) # error_occurred
        return

    my_username_str = get_username_as_str(my_user_account)

    online_users_temp = [
        tt_instance.get_user(username)
        for username in ONLINE_USERS_CACHE.keys()
        if username and username != my_username_str
    ]
    online_users = [user for user in online_users_temp if user]

    if not online_users:
        await message.reply(_("No other users online to select.")) # SHOW_USERS_NO_OTHER_USERS_ONLINE
        return

    # get_tt_user_display_name now expects `_` (translator) as its second argument.
    # The `_` here is the admin's translator.
    sorted_users = sorted(online_users, key=lambda u: get_tt_user_display_name(u, _).lower())

    # Assuming create_user_selection_keyboard is refactored to take `_` instead of language string
    builder = create_user_selection_keyboard(_, sorted_users, command_type)

    command_text_map = {
        "kick": _("Select a user to kick:"), # SHOW_USERS_SELECT_KICK
        "ban": _("Select a user to ban:")  # SHOW_USERS_SELECT_BAN
    }
    reply_text = command_text_map.get(command_type, _("Select a user:")) # SHOW_USERS_SELECT_DEFAULT

    await message.reply(reply_text, reply_markup=builder.as_markup())


@admin_router.message(Command("kick"))
async def kick_command_handler(
    message: Message,
    _: callable,
    tt_instance: TeamTalkInstance | None # From TeamTalkInstanceMiddleware
):
    # IsAdminFilter already applied at router level
    await _show_user_buttons(message, "kick", _, tt_instance)


@admin_router.message(Command("ban"))
async def ban_command_handler(
    message: Message,
    _: callable,
    tt_instance: TeamTalkInstance | None # From TeamTalkInstanceMiddleware
):
    # IsAdminFilter already applied at router level
    await _show_user_buttons(message, "ban", _, tt_instance)


@admin_router.message(Command("subscribers"))
async def subscribers_command_handler(message: Message, session: AsyncSession, _: callable):
    """
    Handles the /subscribers command to display a paginated list of subscribed users.
    Admins only.
    """
    all_subscriber_ids = await get_all_subscribers_ids(session)

    if not all_subscriber_ids:
        await message.reply(_("No subscribers found.")) # SUBSCRIBERS_NONE_FOUND
        return

    current_page = 0  # Initial page
    total_pages = (len(all_subscriber_ids) + SUBSCRIBERS_PER_PAGE - 1) // SUBSCRIBERS_PER_PAGE

    start_index = current_page * SUBSCRIBERS_PER_PAGE
    end_index = start_index + SUBSCRIBERS_PER_PAGE
    page_subscriber_ids = all_subscriber_ids[start_index:end_index]

    keyboard = create_subscriber_list_keyboard(
        _,
        subscriber_ids=page_subscriber_ids,
        current_page=current_page,
        total_pages=total_pages
    )

    await message.reply(
        _("Here is the list of subscribers. Page {current_page_display}/{total_pages}").format(
            current_page_display=current_page + 1,
            total_pages=total_pages
        ), # SUBSCRIBERS_LIST_HEADER
        reply_markup=keyboard
    )
