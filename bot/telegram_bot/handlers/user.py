import logging
import asyncio
import gettext # For type hinting translator
from aiogram import Router, html
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.utils import build_help_message, get_online_teamtalk_users # get_online_teamtalk_users might need tt_connection.instance
import pytalk
# from pytalk.instance import TeamTalkInstance # Will use tt_connection.instance
from pytalk.user import User as TeamTalkUser
# from pytalk.exceptions import TeamTalkException as PytalkTeamTalkException # Not used

from aiogram.exceptions import TelegramAPIError
from bot.telegram_bot.utils import safe_delete_message
from bot.telegram_bot.deeplink import handle_deeplink_payload
from bot.models import UserSettings
from bot.telegram_bot.models import WhoUser, WhoChannelGroup # Used by helpers
from bot.telegram_bot.keyboards import create_main_settings_keyboard, create_main_menu_keyboard
from bot.core.utils import get_tt_user_display_name
# from bot.state import ADMIN_IDS_CACHE # Will use app.admin_ids_cache
from bot.constants import (
    WHO_CHANNEL_ID_ROOT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT2
)
from bot.teamtalk_bot.connection import TeamTalkConnection # For type hinting

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application


logger = logging.getLogger(__name__)
user_commands_router = Router(name="user_commands_router")
# Note: TeamTalkConnectionCheckMiddleware is applied globally in Application setup for now.
# If some user commands don't need TT connection, this router could have it applied selectively,
# or the global middleware in Application could be removed and added per-router.

ttstr = pytalk.instance.sdk.ttstr # Keep for _get_user_display_channel_name


@user_commands_router.message(Command("start"))
async def start_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    app: "Application" # Added app for potential future use, though not used in this handler yet
):
    if not message.from_user:
        return

    token = command.args
    if token:
        # handle_deeplink_payload might need app or tt_connection if it interacts with them
        # For now, assuming its existing signature is sufficient or it will be adapted separately.
        await handle_deeplink_payload(message, token, session, _, user_settings, app) # Pass app
    else:
        await message.reply(_("Hello! Use /help to see available commands."))


# _get_user_display_channel_name and _group_users_for_who_command are helper functions for "who"
# They don't directly take `app` or `tt_connection` but are called by `who_command_handler`
# which will provide necessary parts like `is_caller_admin` (derived from `app.admin_ids_cache`)
# and `tt_instance` (from `tt_connection.instance`).

def _get_user_display_channel_name(
    user_obj: TeamTalkUser,
    is_caller_admin: bool,
    translator: "gettext.GNUTranslations"
    # No direct change here, but caller `who_command_handler` will pass correct `is_caller_admin`
) -> str:
    channel_obj = user_obj.channel
    user_display_channel_name = ""
    is_channel_hidden = False

    if channel_obj:
        try:
            # Ensure pytalk.instance.sdk.ChannelType is correctly referenced
            if hasattr(pytalk.instance.sdk, "ChannelType") and \
               hasattr(channel_obj, 'channel_type') and \
               isinstance(channel_obj.channel_type, int) and \
               (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN) != 0:
                is_channel_hidden = True
        except AttributeError: # Catches missing ChannelType or channel_obj.channel_type
            logger.warning(f"SDK, ChannelType or channel_type attribute missing, cannot determine if channel {ttstr(channel_obj.name)} ({channel_obj.id}) is hidden.")
        except TypeError as e_chan_type:
            logger.error(f"TypeError checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan_type}", exc_info=True)
        except Exception as e_chan:
            logger.error(f"Unexpected error checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan}", exc_info=True)

    if channel_obj and channel_obj.id not in [WHO_CHANNEL_ID_ROOT, WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]:
        if is_caller_admin or not is_channel_hidden:
            user_display_channel_name = translator.gettext("in {channel_name}").format(channel_name=ttstr(channel_obj.name))
        else:
            user_display_channel_name = translator.gettext("under server")
    elif channel_obj and channel_obj.id == WHO_CHANNEL_ID_ROOT:
        user_display_channel_name = translator.gettext("in root channel")
    elif not channel_obj or (hasattr(channel_obj, 'id') and channel_obj.id in [WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]):
        user_display_channel_name = translator.gettext("under server")
    else: # Should ideally not be reached if channel_obj exists and ID is checked
        user_display_channel_name = translator.gettext("in unknown location")

    return user_display_channel_name


def _group_users_for_who_command(
    users: list[TeamTalkUser],
    bot_user_id: int | None, # Bot user ID can be None if not found
    is_caller_admin: bool,
    translator: "gettext.GNUTranslations"
    # No direct change here, but caller `who_command_handler` passes correct args
) -> tuple[list[WhoChannelGroup], int]:
    channels_display_data: dict[str, list[str]] = {}
    users_added_to_groups_count = 0

    for user_obj in users:
        if bot_user_id is not None and user_obj.id == bot_user_id and not is_caller_admin:
            continue

        user_display_channel_name = _get_user_display_channel_name(user_obj, is_caller_admin, translator)

        if user_display_channel_name not in channels_display_data:
            channels_display_data[user_display_channel_name] = []

        user_nickname = get_tt_user_display_name(user_obj, translator) # This helper is fine
        channels_display_data[user_display_channel_name].append(html.quote(user_nickname))
        users_added_to_groups_count += 1

    result_groups = [
        WhoChannelGroup(
            channel_name=name,
            users=[WhoUser(nickname=nick) for nick in nicks]
        )
        for name, nicks in channels_display_data.items()
    ]
    return result_groups, users_added_to_groups_count


def _format_who_message(grouped_data: list[WhoChannelGroup], total_users: int, translator: "gettext.GNUTranslations", server_host: str | None) -> str:
    if total_users == 0:
        no_users_text = translator.gettext("No users found online")
        if server_host:
            no_users_text += translator.gettext(" on server {server_host}").format(server_host=server_host)
        return no_users_text + "."

    sorted_groups = sorted(grouped_data, key=lambda group: group.channel_name)
    users_word_total = translator.ngettext("user", "users", total_users)

    text_reply_header = translator.gettext("There are {user_count} {users_word} on the server")
    if server_host:
        text_reply_header += translator.gettext(" {server_host}")
    text_reply_header += ":\n"
    text_reply = text_reply_header.format(user_count=total_users, users_word=users_word_total, server_host=server_host or "")


    channel_info_parts: list[str] = []
    for group in sorted_groups:
        sorted_nicknames = sorted([user.nickname for user in group.users])
        user_text_segment = ""
        if sorted_nicknames:
            if len(sorted_nicknames) > 1:
                user_separator = translator.gettext(" and ")
                user_list_except_last_segment = ", ".join(sorted_nicknames[:-1])
                user_text_segment = f"<b>{user_list_except_last_segment}{user_separator}{sorted_nicknames[-1]}</b>"
            else:
                user_text_segment = f"<b>{sorted_nicknames[0]}</b>"
            channel_info_parts.append(f"{user_text_segment} {group.channel_name}")

    if channel_info_parts:
        text_reply += "\n" + "\n".join(channel_info_parts)
    return text_reply


@user_commands_router.message(Command("who"))
async def who_command_handler(
    message: Message,
    translator: "gettext.GNUTranslations", # Comes from UserSettingsMiddleware
    app: "Application", # Comes from ApplicationMiddleware
    tt_connection: TeamTalkConnection | None # Comes from ActiveTeamTalkConnectionMiddleware
                                         # Checked by TeamTalkConnectionCheckMiddleware
):
    if not message.from_user:
        return

    # TeamTalkConnectionCheckMiddleware should ensure tt_connection and tt_connection.instance are valid
    if not tt_connection or not tt_connection.instance: # Should ideally not be hit if middleware is correct
        await message.reply(translator.gettext("TeamTalk connection is not available at the moment."))
        return

    tt_instance = tt_connection.instance
    server_host_for_log_and_display = tt_connection.server_info.host

    try:
        # Use connection's cache or fetch via its instance
        # get_online_teamtalk_users helper should be adapted if it used global state.
        # Assuming get_online_teamtalk_users now correctly uses tt_instance passed to it.
        all_users_list = await get_online_teamtalk_users(tt_instance)
    except Exception as e: # Catch a broader range of exceptions during user list retrieval
        logger.error(f"Error getting user list for /who on server {server_host_for_log_and_display}: {e}", exc_info=True)
        await message.reply(translator.gettext("An internal error occurred while retrieving the user list."))
        return

    is_caller_admin = message.from_user.id in app.admin_ids_cache
    bot_user_id = tt_instance.getMyUserID()
    # bot_user_id can be None if not logged in, but middleware should prevent that state.

    if bot_user_id is None: # Defensive check
        logger.error(f"Could not get bot's own user ID from TeamTalk instance on server {server_host_for_log_and_display}.")
        await message.reply(translator.gettext("An error occurred while processing your request."))
        return

    # Run blocking synchronous code in a separate thread
    grouped_data, total_users_to_display = await asyncio.to_thread(
        _group_users_for_who_command,
        all_users_list,
        bot_user_id,
        is_caller_admin,
        translator
    )

    formatted_message = await asyncio.to_thread(
        _format_who_message, grouped_data, total_users_to_display, translator, server_host_for_log_and_display
    )

    await message.reply(formatted_message, parse_mode="HTML")


@user_commands_router.message(Command("help"))
async def help_command_handler(
    message: Message,
    _: callable, # Translator function
    app: "Application" # Get app instance
):
    if not message.from_user: # Should not happen for user commands
        return

    is_telegram_admin = message.from_user.id in app.admin_ids_cache # Use app's cache

    # build_help_message might need adaptation if it relies on global state for TT admin check
    # For now, is_teamtalk_admin is passed as False. If needed, it could check tt_connection.instance.is_admin()
    # This would require tt_connection to be passed here, and this command to have TT conn check middleware.
    help_text = build_help_message(_, "telegram", is_telegram_admin=is_telegram_admin, is_teamtalk_admin=False)
    await message.reply(help_text, parse_mode="HTML")


@user_commands_router.message(Command("settings"))
async def settings_command_handler(
    message: Message,
    _: callable,
    app: "Application" # Added app for future use or consistency
):
    if not message.from_user:
        return

    # This command does not interact with TeamTalk, so tt_connection is not strictly needed here
    # unless settings were to show server-specific info.
    await safe_delete_message(message, log_context_message="user settings command")
    settings_builder = create_main_settings_keyboard(_)
    try:
        await message.answer(
            text=_("Settings"),
            reply_markup=settings_builder.as_markup()
        )
    except TelegramAPIError as e:
        logger.error(f"Could not send settings menu: {e}")


@user_commands_router.message(Command("menu"))
async def menu_command_handler(
    message: Message,
    _: callable,
    app: "Application" # Get app instance
):
    if not message.from_user:
        return

    await safe_delete_message(message, log_context_message="user menu command")
    is_admin = message.from_user.id in app.admin_ids_cache # Use app's cache
    menu_builder = create_main_menu_keyboard(_, is_admin)
    try:
        await message.answer(
            text=_("Main Menu:"),
            reply_markup=menu_builder.as_markup()
        )
    except TelegramAPIError as e:
        logger.error(f"Could not send main menu: {e}")
