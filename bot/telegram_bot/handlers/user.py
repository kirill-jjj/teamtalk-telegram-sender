import logging
import asyncio
from aiogram import Router, html, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser

from bot.localization import get_text
from bot.telegram_bot.callback_data import SettingsCallback # Import the new factory
from bot.telegram_bot.deeplink import handle_deeplink_payload
from bot.core.user_settings import UserSpecificSettings # For type hint
from bot.telegram_bot.filters import IsAdminFilter # For /who admin view
# from bot.telegram_bot.utils import show_user_buttons # Removed as id_command_handler is removed
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
    language: str
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


def _sort_who_data(channels_data: dict[str, list[str]]) -> tuple[list[str], dict[str, list[str]]]:
    """Sorts channel names and user lists within each channel."""
    sorted_names = sorted(channels_data.keys())
    sorted_user_lists_in_channels: dict[str, list[str]] = {}
    for name in sorted_names:
        sorted_user_lists_in_channels[name] = sorted(channels_data[name])
    return sorted_names, sorted_user_lists_in_channels

@user_commands_router.message(Command("who"))
async def who_command_handler(
    message: Message,
    language: str, # From UserSettingsMiddleware
    tt_instance: TeamTalkInstance | None, # From TeamTalkInstanceMiddleware
    session: AsyncSession # From DbSessionMiddleware
):
    if not message.from_user: return

    if not tt_instance or not tt_instance.connected or not tt_instance.logged_in:
        await message.reply(get_text("TT_BOT_NOT_CONNECTED", language))
        return

    try:
        all_users_list = tt_instance.server.get_users()
    except Exception as e:
        logger.error(f"Failed to get users from TT for /who: {e}")
        await message.reply(get_text("TT_ERROR_GETTING_USERS", language))
        return

    # Check if the calling user is an admin for potentially different views
    is_caller_admin_val = await IsAdminFilter()(message, session) # Call the filter directly

    users_to_display_count_val = 0
    # Store as: {channel_display_name: [user_nick1, user_nick2]}
    channels_display_data_val: dict[str, list[str]] = {}

    for user_obj in all_users_list:
        # Skip the bot itself from the list, unless an admin is asking (they might want to see it)
        if user_obj.id == tt_instance.getMyUserID() and not is_caller_admin_val:
            continue

        user_display_channel_name_val = _get_user_display_channel_name(user_obj, is_caller_admin_val, language)

        if user_display_channel_name_val not in channels_display_data_val:
            channels_display_data_val[user_display_channel_name_val] = []

        user_nickname_val = ttstr(user_obj.nickname) or ttstr(user_obj.username) or get_text("WHO_USER_UNKNOWN", language)
        channels_display_data_val[user_display_channel_name_val].append(html.quote(user_nickname_val))
        users_to_display_count_val += 1


    user_count_val = users_to_display_count_val

    # Perform sorting in a separate thread to avoid blocking asyncio event loop
    sorted_channel_names, sorted_users_in_channels = await asyncio.to_thread(
        _sort_who_data, channels_display_data_val
    )

    channel_info_parts_val = []

    for display_channel_name_val in sorted_channel_names:
        users_in_channel_list_val = sorted_users_in_channels[display_channel_name_val]

        user_text_segment_val = ""
        if users_in_channel_list_val:
            if len(users_in_channel_list_val) > 1:
                user_separator_val = get_text("WHO_AND_SEPARATOR", language)
                # Join all but the last with comma, then add separator and the last one
                user_list_except_last_segment_val = ", ".join(users_in_channel_list_val[:-1])
                user_text_segment_val = f"{user_list_except_last_segment_val}{user_separator_val}{users_in_channel_list_val[-1]}"
            else: # Single user in this category
                user_text_segment_val = users_in_channel_list_val[0]
            channel_info_parts_val.append(f"<b>{user_text_segment_val}</b> {display_channel_name_val}") # Usernames bold

    # Determine the correct plural form for "user"
    users_word_total_val = ""
    if language == "ru":
        last_digit = user_count_val % 10
        last_two_digits = user_count_val % 100
        if 11 <= last_two_digits <= 19:
            users_word_total_val = get_text("WHO_USERS_COUNT_PLURAL_5_MORE", "ru")
        elif last_digit == 1:
            users_word_total_val = get_text("WHO_USERS_COUNT_SINGULAR", "ru")
        elif 2 <= last_digit <= 4:
            users_word_total_val = get_text("WHO_USERS_COUNT_PLURAL_2_4", "ru")
        else:
            users_word_total_val = get_text("WHO_USERS_COUNT_PLURAL_5_MORE", "ru")
    else: # en and default
        users_word_total_val = get_text("WHO_USERS_COUNT_SINGULAR", "en") if user_count_val == 1 else get_text("WHO_USERS_COUNT_PLURAL_5_MORE", "en")

    text_reply = get_text("WHO_HEADER", language, user_count=user_count_val, users_word=users_word_total_val)

    if channel_info_parts_val:
        text_reply += "\n".join(channel_info_parts_val)
    elif user_count_val == 0 : # No users at all (after filtering bot itself)
         text_reply = get_text("WHO_NO_USERS_ONLINE", language) # Override header if truly no one
    # If user_count_val > 0 but channel_info_parts_val is empty, it means users are in uncategorized state (should be rare)

    await message.reply(text_reply, parse_mode="HTML")


# id_command_handler removed


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

    # Create buttons
    lang_button = InlineKeyboardButton(
        text=get_text("SETTINGS_BTN_LANGUAGE", language),
        callback_data=SettingsCallback(action="language").pack()
    )
    subscription_button = InlineKeyboardButton(
        text=get_text("SETTINGS_BTN_SUBSCRIPTIONS", language),
        callback_data=SettingsCallback(action="subscriptions").pack()
    )
    notifications_button = InlineKeyboardButton(
        text=get_text("SETTINGS_BTN_NOTIFICATIONS", language),
        callback_data=SettingsCallback(action="notifications").pack()
    )

    # Create keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [lang_button],
        [subscription_button],
        [notifications_button]
    ])

    # Send settings menu
    try:
        await message.answer(
            text=get_text("SETTINGS_MENU_HEADER", language),
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Could not send settings menu: {e}")
