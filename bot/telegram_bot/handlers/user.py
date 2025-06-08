import logging
import asyncio
from aiogram import Router, html
from aiogram.filters import Command, CommandObject
from aiogram.types import Message # InlineKeyboardMarkup, InlineKeyboardButton removed for now, add back if needed for type hints elsewhere
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.utils import pluralize, build_help_message
import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser

# from bot.localization import get_text # Removed
from bot.telegram_bot.deeplink import handle_deeplink_payload # Will take `_`
from bot.core.user_settings import UserSpecificSettings # For type hint
from bot.telegram_bot.filters import IsAdminFilter # For /who admin view
from bot.telegram_bot.keyboards import create_main_settings_keyboard
from bot.core.utils import get_tt_user_display_name
from bot.state import ONLINE_USERS_CACHE
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
    session: AsyncSession, # From DbSessionMiddleware
    _: callable, # Changed from language: str
    user_specific_settings: UserSpecificSettings # From UserSettingsMiddleware
):
    if not message.from_user: return

    token_val = command.args
    if token_val:
        # Assuming handle_deeplink_payload is refactored to take `_`
        await handle_deeplink_payload(message, token_val, session, _, user_specific_settings)
    else:
        await message.reply(_("Hello! Use /help to see available commands.")) # START_HELLO


def _get_user_display_channel_name(
    user_obj: TeamTalkUser,
    is_caller_admin: bool,
    _: callable # Changed from language: str
) -> str:
    channel_obj = user_obj.channel
    user_display_channel_name_val = ""
    is_channel_hidden_val = False

    if channel_obj:
        try:
            # Check if channel is hidden (requires pytalk.instance.sdk.ChannelType)
            if hasattr(pytalk.instance.sdk, "ChannelType") and \
               (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN) != 0:
                is_channel_hidden_val = True
        except AttributeError:
            logger.warning(f"SDK or ChannelType attribute missing, cannot determine if channel {ttstr(channel_obj.name)} ({channel_obj.id}) is hidden.")
        except Exception as e_chan:
            logger.error(f"Error checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan}")

    # Determine display name based on admin status and channel visibility/type
    if channel_obj and channel_obj.id not in [WHO_CHANNEL_ID_ROOT, WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]: # Regular channel
        if is_caller_admin or not is_channel_hidden_val:
            user_display_channel_name_val = _("in {channel_name}").format(channel_name=ttstr(channel_obj.name)) # WHO_CHANNEL_IN
        else: # Hidden channel, non-admin caller
            user_display_channel_name_val = _("under server") # WHO_CHANNEL_UNDER_SERVER
    elif channel_obj and channel_obj.id == WHO_CHANNEL_ID_ROOT: # Root channel
        user_display_channel_name_val = _("in root channel") # WHO_CHANNEL_ROOT
    elif not channel_obj or channel_obj.id in [WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]: # No specific channel / under server
        user_display_channel_name_val = _("under server") # WHO_CHANNEL_UNDER_SERVER
    else: # Fallback for any other case
        user_display_channel_name_val = _("in unknown location") # WHO_CHANNEL_UNKNOWN_LOCATION

    return user_display_channel_name_val


def _group_users_for_who_command(
    users: list[TeamTalkUser],
    bot_user_id: int,
    is_caller_admin: bool,
    _: callable # Changed from lang: str
) -> tuple[dict[str, list[str]], int]:
    """Groups users by channel display name for the /who command."""
    channels_display_data: dict[str, list[str]] = {}
    users_added_to_groups_count = 0

    for user_obj in users:
        if user_obj.id == bot_user_id and not is_caller_admin:
            continue

        user_display_channel_name = _get_user_display_channel_name(user_obj, is_caller_admin, _) # Pass _

        if user_display_channel_name not in channels_display_data:
            channels_display_data[user_display_channel_name] = []

        user_nickname = get_tt_user_display_name(user_obj, _) # Pass _
        channels_display_data[user_display_channel_name].append(html.quote(user_nickname))
        users_added_to_groups_count += 1

    return channels_display_data, users_added_to_groups_count


def _format_who_message(grouped_data: dict[str, list[str]], total_users: int, _: callable) -> str: # Changed lang to _
    """Formats the /who command's reply message."""
    if total_users == 0:
        return _("No users found online.") # WHO_NO_USERS_ONLINE

    sorted_channel_names = sorted(grouped_data.keys())
    sorted_users_in_channels: dict[str, list[str]] = {}
    for name in sorted_channel_names:
        sorted_users_in_channels[name] = sorted(grouped_data[name])

    # Using simple English pluralization, or rely on gettext providing correct plural form for "users"
    # The `pluralize` function is language-specific in its current form.
    # For gettext, you'd typically use `ngettext`. Here, we simplify.
    users_word_total = _("user") if total_users == 1 else _("users")
    # For Russian, the keys were:
    # "WHO_USERS_COUNT_SINGULAR": "пользователь"
    # "WHO_USERS_COUNT_PLURAL_2_4": "пользователя"
    # "WHO_USERS_COUNT_PLURAL_5_MORE": "пользователей"
    # If using ngettext, it would be: ngettext("user", "users", total_users) which then needs .po entries.
    # For now, this will use the singular/plural of the current language based on `_("user")` and `_("users")` keys.

    text_reply = _("There are {user_count} {users_word} on the server:\n").format(user_count=total_users, users_word=users_word_total) # WHO_HEADER

    channel_info_parts: list[str] = []
    for display_channel_name in sorted_channel_names:
        users_in_channel_list = sorted_users_in_channels[display_channel_name]
        user_text_segment = ""
        if users_in_channel_list:
            if len(users_in_channel_list) > 1:
                user_separator = _(" and ") # WHO_AND_SEPARATOR
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
    _: callable, # Changed from language: str
    tt_instance: TeamTalkInstance | None,
    session: AsyncSession,
    data: dict[str, Any] # Middleware might pass _ via data as well
):
    # If _ is not passed directly by DI, get from data (safer)
    # _ = data.get("_", get_translator("en").gettext) # Fallback, assuming get_translator available
    # For this refactor, assuming _ is passed directly as per signature change.

    if not message.from_user:
        return

    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await message.reply(_("TeamTalk bot is not connected.")) # TT_BOT_NOT_CONNECTED
        return

    try:
        all_users_list = list(ONLINE_USERS_CACHE.values())
    except Exception as e:
        logger.error(f"Failed to get user objects from ONLINE_USERS_CACHE for /who: {e}", exc_info=True)
        await message.reply(_("Error getting users from TeamTalk.")) # TT_ERROR_GETTING_USERS
        return

    is_caller_admin_val = await IsAdminFilter()(message, session)
    bot_user_id = tt_instance.getMyUserID()
    if bot_user_id is None:
        logger.error("Could not get bot's own user ID from TeamTalk instance.")
        await message.reply(_("An error occurred.")) # error_occurred
        return

    grouped_data, total_users_to_display = await asyncio.to_thread(
        _group_users_for_who_command,
        all_users_list,
        bot_user_id,
        is_caller_admin_val,
        _ # Pass translator
    )

    formatted_message = await asyncio.to_thread(
        _format_who_message, grouped_data, total_users_to_display, _ # Pass translator
    )

    await message.reply(formatted_message, parse_mode="HTML")


@user_commands_router.message(Command("help"))
async def help_command_handler(
    message: Message,
    _: callable, # Changed from language: str
    session: AsyncSession,
    data: dict[str, Any] # For is_bot_admin if needed from user_specific_settings
):
    # _ = data["_"] # If _ is not passed directly
    is_admin = await IsAdminFilter()(message, session) # This checks if TG user is a bot admin
    # build_help_message expects: _, platform, is_admin (TT server admin), is_bot_admin (bot admin)
    # Assuming IsAdminFilter result means they are a bot admin.
    # For is_admin (TT server admin status), we don't have that info here directly.
    # For Telegram platform, is_admin (TT) is likely not relevant.
    help_text = build_help_message(_, "telegram", is_admin, is_admin) # Passing is_admin for both admin flags
    await message.reply(help_text, parse_mode="HTML")


@user_commands_router.message(Command("settings"))
async def settings_command_handler(
    message: Message,
    _: callable, # Changed from language: str
    data: dict[str, Any] # For _ if not direct param
):
    # _ = data["_"] # If _ is not passed directly
    if not message.from_user: return

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user settings command: {e}")

    # Assuming create_main_settings_keyboard is refactored to take `_`
    settings_builder = create_main_settings_keyboard(_)

    try:
        await message.answer(
            text=_("⚙️ Settings"), # SETTINGS_MENU_HEADER
            reply_markup=settings_builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Could not send settings menu: {e}")
