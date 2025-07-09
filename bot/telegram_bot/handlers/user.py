"""Telegram bot command handlers for regular user interactions."""

import asyncio
import functools  # Moved import functools to the top
import gettext  # For type hinting translator
from html import escape
import logging

# For type hinting Services
from typing import (
    TYPE_CHECKING,  # For admin_ids_cache type hint
)

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
import pytalk
from pytalk.user import User as TeamTalkUser
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import (
    WHO_CHANNEL_ID_ROOT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT2,
)
from bot.core.utils import build_help_message
from bot.models import UserSettings
from bot.teamtalk_bot.connection import TeamTalkConnection  # For type hinting
from bot.teamtalk_bot.utils import get_online_teamtalk_users, get_tt_user_display_name  # Updated imports
from bot.telegram_bot.deeplink import handle_deeplink_payload
from bot.telegram_bot.keyboards import create_main_menu_keyboard, create_main_settings_keyboard
from bot.telegram_bot.models import WhoChannelGroup, WhoUser
from bot.telegram_bot.utils import safe_delete_message

if TYPE_CHECKING:
    from bot.services_container import Services

# Middlewares to apply
from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware, TeamTalkConnectionCheckMiddleware

logger = logging.getLogger(__name__)
user_commands_router = Router(name="user_commands_router")
# Apply to the whole router. Specific handlers will use or not use tt_connection.
user_commands_router.message.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
user_commands_router.message.middleware(TeamTalkConnectionCheckMiddleware())

ttstr = pytalk.instance.sdk.ttstr


@user_commands_router.message(Command("start"))
async def start_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    translator: gettext.GNUTranslations,  # gettext function
    user_settings: UserSettings,
    services: "Services",  # Changed from app: "Application"
) -> None:
    """Handles the /start command, processing deeplinks or showing a welcome message."""
    _ = translator.gettext
    if not message.from_user:
        return

    token = command.args
    if token:
        # TODO: Call to handle_deeplink_payload might need review if its own dependencies change.
        await handle_deeplink_payload(message, token, session, translator, user_settings, services)
    else:
        await message.reply(_("Hello! Use /help to see available commands."))


def _get_user_display_channel_name(
    user_obj: TeamTalkUser, *, is_caller_admin: bool, translator: "gettext.GNUTranslations"
) -> str:
    channel_obj = user_obj.channel
    user_display_channel_name = ""
    is_channel_hidden = False

    if channel_obj:
        try:
            if (
                hasattr(pytalk.instance.sdk, "ChannelType")
                and hasattr(channel_obj, "channel_type")
                and isinstance(channel_obj.channel_type, int)
                and (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN) != 0
            ):
                is_channel_hidden = True
        except AttributeError:  # Catches missing ChannelType or channel_obj.channel_type
            log_msg = (
                f"SDK, ChannelType or channel_type attribute missing, "
                f"cannot determine if channel {ttstr(channel_obj.name)} ({channel_obj.id}) is hidden."
            )
            logger.warning(log_msg)
        except TypeError as e_chan_type:
            log_msg = f"TypeError checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan_type}"
            logger.exception(log_msg)
        except Exception as e_chan:
            log_msg = (
                f"Unexpected error checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan}"
            )
            logger.exception(log_msg)

    server_root_ids = [WHO_CHANNEL_ID_ROOT, WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]
    if channel_obj and channel_obj.id not in server_root_ids:
        if is_caller_admin or not is_channel_hidden:
            channel_name_str = ttstr(channel_obj.name)
            user_display_channel_name = translator.gettext("in {channel_name}").format(channel_name=channel_name_str)
        else:
            user_display_channel_name = translator.gettext("under server")
    elif channel_obj and channel_obj.id == WHO_CHANNEL_ID_ROOT:
        user_display_channel_name = translator.gettext("in root channel")
    elif not channel_obj or (
        hasattr(channel_obj, "id")
        and channel_obj.id in [WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]
    ):
        user_display_channel_name = translator.gettext("under server")
    else:  # Should ideally not be reached if channel_obj exists and ID is checked
        user_display_channel_name = translator.gettext("in unknown location")

    return user_display_channel_name


def _group_users_for_who_command(
    users: list[TeamTalkUser], bot_user_id: int | None, *, is_caller_admin: bool, translator: "gettext.GNUTranslations"
) -> tuple[list[WhoChannelGroup], int]:
    channels_display_data: dict[str, list[str]] = {}
    users_added_to_groups_count = 0

    for user_obj in users:
        if bot_user_id is not None and user_obj.id == bot_user_id and not is_caller_admin:
            continue

        user_display_channel_name = _get_user_display_channel_name(
            user_obj, is_caller_admin=is_caller_admin, translator=translator
        )

        if user_display_channel_name not in channels_display_data:
            channels_display_data[user_display_channel_name] = []

        user_nickname = get_tt_user_display_name(user_obj, translator)
        channels_display_data[user_display_channel_name].append(escape(user_nickname))
        users_added_to_groups_count += 1

    result_groups = [
        WhoChannelGroup(channel_name=name, users=[WhoUser(nickname=nick) for nick in nicks])
        for name, nicks in channels_display_data.items()
    ]
    return result_groups, users_added_to_groups_count


def _format_who_message(
    grouped_data: list[WhoChannelGroup],
    total_users: int,
    translator: "gettext.GNUTranslations",
    server_host: str | None,
) -> str:
    _ = translator.gettext
    ngettext = translator.ngettext

    if total_users == 0:
        no_users_text = _("No users found online")
        if server_host:
            no_users_text = _("No users found online on server {server_host}.").format(server_host=server_host)
        else:
            no_users_text = _("No users found online.")
        return no_users_text

    sorted_groups = sorted(grouped_data, key=lambda group: group.channel_name)

    if server_host:
        header_template = ngettext(
            "There is {user_count} user on the server {server_host}:\n",
            "There are {user_count} users on the server {server_host}:\n",
            total_users,
        )
        text_reply = header_template.format(user_count=total_users, server_host=server_host)
    else:
        header_template = ngettext(
            "There is {user_count} user on the server:\n", "There are {user_count} users on the server:\n", total_users
        )
        text_reply = header_template.format(user_count=total_users)

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
    translator: "gettext.GNUTranslations",  # Injected by UserSettingsMiddleware
    services: "Services",  # Injected from workflow_data
    tt_connection: TeamTalkConnection | None,  # Injected by ActiveTeamTalkConnectionMiddleware
) -> None:
    """Handles the /who command, showing online users in TeamTalk."""
    if not message.from_user:
        return

    if not tt_connection or not tt_connection.instance:
        await message.reply(translator.gettext("TeamTalk connection is not available. Please try again later."))
        return

    tt_instance = tt_connection.instance
    server_host_for_log_and_display = tt_connection.server_info.host

    try:
        all_users_list = await get_online_teamtalk_users(tt_instance)
    except Exception as e:
        # Keep f-string for log_msg as it's constructing a message before logging
        log_msg = f"Error getting user list for /who on server {server_host_for_log_and_display}: {e}"
        logger.exception(log_msg)
        await message.reply(translator.gettext("An error occurred. Please try again later."))
        return

    is_caller_admin = services.cache.is_admin(message.from_user.id)
    bot_user_id = tt_instance.getMyUserID()

    if bot_user_id is None:
        log_msg = f"Could not get bot's own user ID from TeamTalk instance on server {server_host_for_log_and_display}."
        logger.error(log_msg)
        await message.reply(translator.gettext("An error occurred. Please try again later."))
        return

    # Prepare the function call with keyword arguments
    func_to_run_in_thread = functools.partial(
        _group_users_for_who_command,
        is_caller_admin=is_caller_admin,
        translator=translator
    )
    # Pass only positional arguments to to_thread
    grouped_data, total_users_to_display = await asyncio.to_thread(
        func_to_run_in_thread, all_users_list, bot_user_id
    )

    # Prepare the function call with keyword arguments for _format_who_message
    format_func_to_run_in_thread = functools.partial(
        _format_who_message,
        translator=translator,
        server_host=server_host_for_log_and_display
    )
    # Pass only positional arguments to to_thread
    formatted_message = await asyncio.to_thread(
        format_func_to_run_in_thread, grouped_data, total_users_to_display
    )

    await message.reply(formatted_message)


@user_commands_router.message(Command("help"))
async def help_command_handler(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    services: "Services",  # Injected from workflow_data
) -> None:
    """Handles the /help command, showing available commands."""
    _ = translator.gettext
    if not message.from_user:
        return

    is_telegram_admin = services.cache.is_admin(message.from_user.id)
    help_text = build_help_message(translator, "telegram", is_telegram_admin=is_telegram_admin, is_teamtalk_admin=False)
    await message.reply(help_text)


@user_commands_router.message(Command("settings"))
async def settings_command_handler(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
) -> None:
    """Handles the /settings command, showing the main settings menu."""
    _ = translator.gettext
    if not message.from_user:
        return

    await safe_delete_message(message, log_context_message="user settings command")
    settings_builder = await create_main_settings_keyboard(translator)
    try:
        await message.answer(text=_("Settings"), reply_markup=settings_builder.as_markup())
    except TelegramAPIError:
        logger.exception("Could not send settings menu.")


@user_commands_router.message(Command("menu"))
async def menu_command_handler(
    message: Message,
    translator: gettext.GNUTranslations,  # Injected by UserSettingsMiddleware
    services: "Services",  # Injected from workflow_data
) -> None:
    """Handles the /menu command, showing the main command menu."""
    _ = translator.gettext
    if not message.from_user:
        return

    await safe_delete_message(message, log_context_message="user menu command")
    is_admin = services.cache.is_admin(message.from_user.id)
    # Pass the full translator object to create_main_menu_keyboard
    menu_builder = await create_main_menu_keyboard(translator, is_admin=is_admin)
    try:
        await message.answer(text=_("Main Menu:"), reply_markup=menu_builder.as_markup())
    except TelegramAPIError:
        logger.exception("Could not send main menu.")
