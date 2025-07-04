import logging
import asyncio
import gettext
from aiogram import Router, html
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.utils import build_help_message, get_online_teamtalk_users
import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser
from pytalk.exceptions import TeamTalkException as PytalkTeamTalkException # For /who command

from aiogram.exceptions import TelegramAPIError
from bot.telegram_bot.utils import safe_delete_message # Added import
from bot.telegram_bot.deeplink import handle_deeplink_payload
from bot.models import UserSettings
from bot.telegram_bot.models import WhoUser, WhoChannelGroup
from bot.telegram_bot.keyboards import create_main_settings_keyboard, create_main_menu_keyboard
from bot.core.utils import get_tt_user_display_name
from bot.state import ADMIN_IDS_CACHE
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
    if not message.from_user:
        return

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
) -> tuple[list[WhoChannelGroup], int]:
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

    result_groups = [
        WhoChannelGroup(
            channel_name=name,
            users=[WhoUser(nickname=nick) for nick in nicks]
        )
        for name, nicks in channels_display_data.items()
    ]

    return result_groups, users_added_to_groups_count


def _format_who_message(grouped_data: list[WhoChannelGroup], total_users: int, translator: "gettext.GNUTranslations") -> str:
    """Formats the /who command's reply message."""
    if total_users == 0:
        return translator.gettext("No users found online.")

    # Sort groups by channel name
    sorted_groups = sorted(grouped_data, key=lambda group: group.channel_name)

    users_word_total = translator.ngettext("user", "users", total_users)
    text_reply = translator.gettext("There are {user_count} {users_word} on the server:\n").format(user_count=total_users, users_word=users_word_total)

    channel_info_parts: list[str] = []
    for group in sorted_groups:
        # Sort users within each group by nickname
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
    except (AttributeError, TypeError, RuntimeError) as e:
        logger.error(f"Error processing ONLINE_USERS_CACHE for /who command: {e}", exc_info=True)
        await message.reply(translator.gettext("An internal error occurred while retrieving the user list."))
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
    is_telegram_admin = message.from_user.id in ADMIN_IDS_CACHE if message.from_user else False

    help_text = build_help_message(_, "telegram", is_telegram_admin=is_telegram_admin, is_teamtalk_admin=False)
    await message.reply(help_text, parse_mode="HTML")


@user_commands_router.message(Command("settings"))
async def settings_command_handler(
    message: Message,
    _: callable
):
    if not message.from_user:
        return

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
    _: callable
):
    if not message.from_user:
        return

    await safe_delete_message(message, log_context_message="user menu command")

    is_admin = message.from_user.id in ADMIN_IDS_CACHE
    menu_builder = create_main_menu_keyboard(_, is_admin)

    try:
        await message.answer(
            text=_("Main Menu:"),
            reply_markup=menu_builder.as_markup()
        )
    except TelegramAPIError as e:
        logger.error(f"Could not send main menu: {e}")
