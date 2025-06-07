import logging
import asyncio
from aiogram import Router, html
from aiogram.filters import Command, CommandObject
from aiogram.types import Message # InlineKeyboardMarkup, InlineKeyboardButton removed for now, add back if needed for type hints elsewhere
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.utils import pluralize
import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser

from bot.localization import get_text
from bot.telegram_bot.deeplink import handle_deeplink_payload
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
    language: str, # From UserSettingsMiddleware
    user_specific_settings: UserSpecificSettings # From UserSettingsMiddleware
):
    if not message.from_user: return # Should not happen with Command filter

    token_val = command.args
    if token_val:
        await handle_deeplink_payload(message, token_val, session, language, user_specific_settings)
    else:
        await message.reply(get_text("START_HELLO", language))


def _get_user_display_channel_name(
    user_obj: TeamTalkUser,
    is_caller_admin: bool,
    language: str # Renamed from lang to language for consistency
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
            user_display_channel_name_val = get_text("WHO_CHANNEL_IN", language, channel_name=ttstr(channel_obj.name))
        else: # Hidden channel, non-admin caller
            user_display_channel_name_val = get_text("WHO_CHANNEL_UNDER_SERVER", language)
    elif channel_obj and channel_obj.id == WHO_CHANNEL_ID_ROOT: # Root channel
        user_display_channel_name_val = get_text("WHO_CHANNEL_ROOT", language)
    elif not channel_obj or channel_obj.id in [WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]: # No specific channel / under server
        user_display_channel_name_val = get_text("WHO_CHANNEL_UNDER_SERVER", language)
    else: # Fallback for any other case
        user_display_channel_name_val = get_text("WHO_CHANNEL_UNKNOWN_LOCATION", language)

    return user_display_channel_name_val


def _group_users_for_who_command(
    users: list[TeamTalkUser],
    bot_user_id: int,
    is_caller_admin: bool,
    lang: str
) -> tuple[dict[str, list[str]], int]:
    """Groups users by channel display name for the /who command."""
    channels_display_data: dict[str, list[str]] = {}
    users_added_to_groups_count = 0

    for user_obj in users:
        if user_obj.id == bot_user_id and not is_caller_admin:
            continue

        user_display_channel_name = _get_user_display_channel_name(user_obj, is_caller_admin, lang)

        if user_display_channel_name not in channels_display_data:
            channels_display_data[user_display_channel_name] = []

        user_nickname = get_tt_user_display_name(user_obj, lang)
        channels_display_data[user_display_channel_name].append(html.quote(user_nickname)) # html.quote here
        users_added_to_groups_count += 1

    return channels_display_data, users_added_to_groups_count


def _format_who_message(grouped_data: dict[str, list[str]], total_users: int, lang: str) -> str:
    """Formats the /who command's reply message."""
    if total_users == 0:
        return get_text("WHO_NO_USERS_ONLINE", lang)

    # Sort data (incorporates _sort_who_data logic)
    sorted_channel_names = sorted(grouped_data.keys())
    # Nicknames in grouped_data are already html.quoted and will be sorted as such.
    # Sorting user lists within channels:
    sorted_users_in_channels: dict[str, list[str]] = {}
    for name in sorted_channel_names:
        # Users are already quoted, sorting will be based on quoted strings
        sorted_users_in_channels[name] = sorted(grouped_data[name])

    # Determine pluralization for "user" using the new pluralize function
    if lang == "ru":
        users_word_total = pluralize(
            total_users,
            one=get_text("WHO_USERS_COUNT_SINGULAR", lang),    # e.g., "пользователь"
            few=get_text("WHO_USERS_COUNT_PLURAL_2_4", lang),  # e.g., "пользователя"
            many=get_text("WHO_USERS_COUNT_PLURAL_5_MORE", lang) # e.g., "пользователей"
        )
    else:  # en and default
        users_word_total = get_text("WHO_USERS_COUNT_SINGULAR", lang) if total_users == 1 else get_text("WHO_USERS_COUNT_PLURAL_5_MORE", lang)

    text_reply = get_text("WHO_HEADER", lang, user_count=total_users, users_word=users_word_total)

    channel_info_parts: list[str] = []
    for display_channel_name in sorted_channel_names:
        users_in_channel_list = sorted_users_in_channels[display_channel_name] # These are already html.quoted
        user_text_segment = ""
        if users_in_channel_list:
            if len(users_in_channel_list) > 1:
                user_separator = get_text("WHO_AND_SEPARATOR", lang)
                # Users are already quoted, so direct join is fine
                user_list_except_last_segment = ", ".join(users_in_channel_list[:-1])
                user_text_segment = f"<b>{user_list_except_last_segment}{user_separator}{users_in_channel_list[-1]}</b>"
            else:  # Single user
                user_text_segment = f"<b>{users_in_channel_list[0]}</b>"
            channel_info_parts.append(f"{user_text_segment} {display_channel_name}")

    if channel_info_parts:
        text_reply += "\n" + "\n".join(channel_info_parts)
    # If no channel_info_parts but total_users > 0, header is sufficient.

    return text_reply


@user_commands_router.message(Command("who"))
async def who_command_handler(
    message: Message,
    language: str, # From UserSettingsMiddleware
    tt_instance: TeamTalkInstance | None, # From TeamTalkInstanceMiddleware
    session: AsyncSession # From DbSessionMiddleware
):
    if not message.from_user:
        return

    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await message.reply(get_text("TT_BOT_NOT_CONNECTED", language))
        return

    try:
        # Reconstruct pytalk.User objects from usernames in the cache
        # tt_instance.get_user(username) is expected to be a fast in-memory lookup
        # if the user object itself is cached by pytalk or if it reconstructs it quickly.
        all_users_list = [tt_instance.get_user(username) for username in ONLINE_USERS_CACHE.keys() if username]
        # Filter out None results if get_user might return None for a cached username
        # that somehow doesn't resolve to a full user object anymore (should be rare if cache is consistent)
        all_users_list = [user for user in all_users_list if user is not None]
    except Exception as e:
        logger.error(f"Failed to get user objects from ONLINE_USERS_CACHE for /who: {e}", exc_info=True)
        await message.reply(get_text("TT_ERROR_GETTING_USERS", language))
        return

    is_caller_admin_val = await IsAdminFilter()(message, session)

    # Use the first helper to group users
    # tt_instance.getMyUserID() can be None if not logged in, but previous checks should prevent this.
    # Adding a type ignore or check if myUserID could be None here.
    bot_user_id = tt_instance.getMyUserID()
    if bot_user_id is None: # Should ideally not happen due to earlier checks
        logger.error("Could not get bot's own user ID from TeamTalk instance.")
        await message.reply(get_text("error_occurred", language)) # Generic error
        return

    # Grouping is synchronous and CPU-bound for the loop part
    # Running _group_users_for_who_command in a separate thread
    grouped_data, total_users_to_display = await asyncio.to_thread(
        _group_users_for_who_command,
        all_users_list,
        bot_user_id,
        is_caller_admin_val,
        language
    )

    # Formatting can also be CPU-bound, especially string operations and sorting
    # Running _format_who_message in a separate thread
    formatted_message = await asyncio.to_thread(
        _format_who_message, grouped_data, total_users_to_display, language
    )

    await message.reply(formatted_message, parse_mode="HTML")


@user_commands_router.message(Command("help"))
async def help_command_handler(message: Message, language: str): # From UserSettingsMiddleware
    await message.reply(get_text("HELP_TEXT", language), parse_mode="Markdown")


@user_commands_router.message(Command("settings"))
async def settings_command_handler(
    message: Message,
    language: str, # From UserSettingsMiddleware
):
    if not message.from_user: return # Should not happen with Command filter

    # Delete user's command
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user settings command: {e}")

    # Create buttons using factory
    settings_builder = create_main_settings_keyboard(language)

    # Send settings menu
    try:
        await message.answer(
            text=get_text("SETTINGS_MENU_HEADER", language),
            reply_markup=settings_builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Could not send settings menu: {e}")
