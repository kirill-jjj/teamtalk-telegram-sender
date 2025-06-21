import logging
import asyncio
import gettext
from typing import Any
from aiogram import Router, html
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.utils import build_help_message, get_online_teamtalk_users # Added import
import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser

from bot.telegram_bot.deeplink import handle_deeplink_payload
from bot.models import UserSettings
from bot.telegram_bot.keyboards import create_main_settings_keyboard
from bot.core.utils import get_tt_user_display_name
from bot.state import ONLINE_USERS_CACHE, ADMIN_IDS_CACHE
from bot.constants import (
    WHO_CHANNEL_ID_ROOT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT2
)


logger = logging.getLogger(__name__)
user_commands_router = Router(name="user_commands_router")
ttstr = pytalk.instance.sdk.ttstr


@user_commands_router.message(Command("start"))
async def start_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings
):
    if not message.from_user: return

    token = command.args
    if token:
        await handle_deeplink_payload(message, token, session, _, user_settings)
    else:
        await message.reply(_("Hello! Use /help to see available commands."))


def _get_user_display_channel_name(
    user_obj: TeamTalkUser,
    is_caller_admin: bool,
    translator: "gettext.GNUTranslations"
) -> str:
    channel_obj = user_obj.channel
    user_display_channel_name = ""
    is_channel_hidden = False

    if channel_obj:
        try:
            if hasattr(pytalk.instance.sdk, "ChannelType") and \
               (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN) != 0:
                is_channel_hidden = True
        except AttributeError:
            logger.warning(f"SDK or ChannelType attribute missing, cannot determine if channel {ttstr(channel_obj.name)} ({channel_obj.id}) is hidden.")
        except Exception as e_chan:
            logger.error(f"Error checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan}")

    if channel_obj and channel_obj.id not in [WHO_CHANNEL_ID_ROOT, WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]:
        if is_caller_admin or not is_channel_hidden:
            user_display_channel_name = translator.gettext("in {channel_name}").format(channel_name=ttstr(channel_obj.name))
        else:
            user_display_channel_name = translator.gettext("under server")
    elif channel_obj and channel_obj.id == WHO_CHANNEL_ID_ROOT:
        user_display_channel_name = translator.gettext("in root channel")
    elif not channel_obj or channel_obj.id in [WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]:
        user_display_channel_name = translator.gettext("under server")
    else:
        user_display_channel_name = translator.gettext("in unknown location")

    return user_display_channel_name


def _group_users_for_who_command(
    users: list[TeamTalkUser],
    bot_user_id: int,
    is_caller_admin: bool,
    translator: "gettext.GNUTranslations"
) -> tuple[dict[str, list[str]], int]:
    """Groups users by channel display name for the /who command."""
    channels_display_data: dict[str, list[str]] = {}
    users_added_to_groups_count = 0

    for user_obj in users:
        if user_obj.id == bot_user_id and not is_caller_admin:
            continue

        user_display_channel_name = _get_user_display_channel_name(user_obj, is_caller_admin, translator)

        if user_display_channel_name not in channels_display_data:
            channels_display_data[user_display_channel_name] = []

        user_nickname = get_tt_user_display_name(user_obj, translator)
        channels_display_data[user_display_channel_name].append(html.quote(user_nickname))
        users_added_to_groups_count += 1

    return channels_display_data, users_added_to_groups_count


def _format_who_message(grouped_data: dict[str, list[str]], total_users: int, translator: "gettext.GNUTranslations") -> str:
    """Formats the /who command's reply message."""
    if total_users == 0:
        return translator.gettext("No users found online.")

    sorted_channel_names = sorted(grouped_data.keys())
    sorted_users_in_channels: dict[str, list[str]] = {}
    for name in sorted_channel_names:
        sorted_users_in_channels[name] = sorted(grouped_data[name])

    # For gettext, ngettext is typically used for pluralization.
    users_word_total = translator.ngettext("user", "users", total_users)
    # This will use the singular/plural forms defined in .po files for the current language.

    text_reply = translator.gettext("There are {user_count} {users_word} on the server:\n").format(user_count=total_users, users_word=users_word_total)

    channel_info_parts: list[str] = []
    for display_channel_name in sorted_channel_names:
        users_in_channel_list = sorted_users_in_channels[display_channel_name]
        user_text_segment = ""
        if users_in_channel_list:
            if len(users_in_channel_list) > 1:
                user_separator = translator.gettext(" and ")
                user_list_except_last_segment = ", ".join(users_in_channel_list[:-1])
                user_text_segment = f"<b>{user_list_except_last_segment}{user_separator}{users_in_channel_list[-1]}</b>"
            else:
                user_text_segment = f"<b>{users_in_channel_list[0]}</b>"
            channel_info_parts.append(f"{user_text_segment} {display_channel_name}")

    if channel_info_parts:
        text_reply += "\n" + "\n".join(channel_info_parts)

    return text_reply


@user_commands_router.message(Command("who"))
async def who_command_handler(
    message: Message,
    _: callable,
    tt_instance: TeamTalkInstance | None,
    translator: "gettext.GNUTranslations"
):
    if not message.from_user:
        return

    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await message.reply(translator.gettext("TeamTalk bot is not connected."))
        return

    try:
        all_users_list = await get_online_teamtalk_users(tt_instance)
    except Exception as e:
        logger.error(f"Failed to get user objects from ONLINE_USERS_CACHE for /who: {e}", exc_info=True) # Log message could be updated
        await message.reply(translator.gettext("Error getting users from TeamTalk."))
        return

    is_caller_admin = message.from_user.id in ADMIN_IDS_CACHE if message.from_user else False
    bot_user_id = tt_instance.getMyUserID()
    if bot_user_id is None:
        logger.error("Could not get bot's own user ID from TeamTalk instance.")
        await message.reply(translator.gettext("An error occurred."))
        return

    grouped_data, total_users_to_display = await asyncio.to_thread(
        _group_users_for_who_command,
        all_users_list,
        bot_user_id,
        is_caller_admin,
        translator
    )

    formatted_message = await asyncio.to_thread(
        _format_who_message, grouped_data, total_users_to_display, translator
    )

    await message.reply(formatted_message, parse_mode="HTML")


@user_commands_router.message(Command("help"))
async def help_command_handler(
    message: Message,
    _: callable
):
    is_admin = message.from_user.id in ADMIN_IDS_CACHE if message.from_user else False # This checks if TG user is a bot admin
    # build_help_message expects: _, platform, is_admin (TT server admin), is_bot_admin (bot admin)
    # Assuming ADMIN_IDS_CACHE check result means they are a bot admin.
    # For is_admin (TT server admin status), we don't have that info here directly.
    # For Telegram platform, is_admin (TT) is likely not relevant.
    help_text = build_help_message(_, "telegram", is_admin, is_admin) # Passing is_admin for both admin flags
    await message.reply(help_text, parse_mode="HTML")


@user_commands_router.message(Command("settings"))
async def settings_command_handler(
    message: Message,
    _: callable
):
    if not message.from_user: return

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user settings command: {e}")

    settings_builder = create_main_settings_keyboard(_)

    try:
        await message.answer(
            text=_("Settings"),
            reply_markup=settings_builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Could not send settings menu: {e}")
