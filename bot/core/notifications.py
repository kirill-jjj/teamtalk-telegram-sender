import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import html
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser

from bot.config import app_config
from bot.localization import get_text
from bot.database.crud import get_all_subscribers_ids
from bot.database.engine import SessionFactory
from bot.core.user_settings import USER_SETTINGS_CACHE, get_or_create_user_settings, UserSpecificSettings
from bot.telegram_bot.utils import send_telegram_messages_to_list
from bot.constants import (
    NOTIFICATION_EVENT_JOIN,
    NOTIFICATION_EVENT_LEAVE,
    WHO_USER_UNKNOWN,
    JOIN_NOTIFICATION,
    LEAVE_NOTIFICATION,
    TOGGLE_IGNORE_BUTTON_TEXT,
    CALLBACK_NICKNAME_MAX_LENGTH,
    INITIAL_LOGIN_IGNORE_DELAY_SECONDS
)
# Import teamtalk_bot.bot_instance carefully
from bot.teamtalk_bot.bot_instance import login_complete_time as global_login_complete_time

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


async def should_notify_user(
    telegram_id: int,
    tt_user_username: str, # TeamTalk username of the user who joined/left
    event_type: str, # "join" or "leave"
    session # For fetching settings if not in cache
) -> bool:
    # Ensure settings are loaded for the recipient
    user_specific_settings = await get_or_create_user_settings(telegram_id, session)

    notification_pref = user_specific_settings.notification_settings
    mute_all_flag = user_specific_settings.mute_all_flag
    muted_users = user_specific_settings.muted_users_set

    if notification_pref == pytalk.database.models.NotificationSetting.NONE: # Use the enum from models
        return False
    if event_type == NOTIFICATION_EVENT_JOIN and notification_pref == pytalk.database.models.NotificationSetting.JOIN_OFF:
        return False
    if event_type == NOTIFICATION_EVENT_LEAVE and notification_pref == pytalk.database.models.NotificationSetting.LEAVE_OFF:
        return False

    # Mute logic
    if mute_all_flag:
        # Notify only if user is an exception (i.e., in the muted_users_set which acts as an allow-list)
        return tt_user_username in muted_users
    else:
        # Notify if user is NOT in the muted_users_set (which acts as a block-list)
        return tt_user_username not in muted_users


def _generate_join_leave_markup(
    tt_user_username: str,
    tt_user_nickname: str, # Nickname of the user who joined/left
    lang_code: str,
    recipient_tg_id: int # Telegram ID of the user receiving the notification
) -> InlineKeyboardMarkup | None:
    # Nickname for button display and callback data (truncated)
    button_display_nickname = html.quote(tt_user_nickname[:CALLBACK_NICKNAME_MAX_LENGTH])
    callback_safe_nickname = tt_user_nickname[:CALLBACK_NICKNAME_MAX_LENGTH] # Raw for callback data

    callback_data = f"toggle_ignore_user:{tt_user_username}:{callback_safe_nickname}"
    button_text = get_text(TOGGLE_IGNORE_BUTTON_TEXT, lang_code, nickname=button_display_nickname)

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_text, callback_data=callback_data)]
    ])


async def send_join_leave_notification_logic(
    event_type: str, # "join" or "leave"
    tt_user: TeamTalkUser, # The TeamTalk user object who joined/left
    tt_instance: TeamTalkInstance # The TT instance this event belongs to
):
    # Check if bot has recently logged in to avoid flood of initial notifications
    if global_login_complete_time is None or \
       datetime.utcnow() < global_login_complete_time + timedelta(seconds=INITIAL_LOGIN_IGNORE_DELAY_SECONDS):
        if event_type == NOTIFICATION_EVENT_JOIN: # Only log for joins during this period
             logger.debug(f"Ignoring potential initial sync {event_type} for {ttstr(tt_user.username)} ({tt_user.id}). Bot login too recent.")
        return

    user_nickname_val = ttstr(tt_user.nickname) or ttstr(tt_user.username) or get_text(WHO_USER_UNKNOWN, "en") # Fallback lang for unknown
    user_username_val = ttstr(tt_user.username)
    user_id_val = tt_user.id # For logging

    if not user_username_val:
        logger.warning(f"User {event_type} with empty username (Nickname: {user_nickname_val}, ID: {user_id_val}). Skipping notification.")
        return

    if app_config.get("GLOBAL_IGNORE_USERNAME") and user_username_val == app_config["GLOBAL_IGNORE_USERNAME"]:
        logger.info(f"User {user_username_val} is globally ignored. Skipping {event_type} notification.")
        return

    # Determine server name
    server_name_val = app_config.get("SERVER_NAME")
    if not server_name_val:
        try:
            if tt_instance and tt_instance.connected:
                server_name_val = ttstr(tt_instance.server.get_properties().server_name)
            else:
                server_name_val = "Unknown Server"
        except Exception as e:
            logger.error(f"Could not get server name for notification: {e}")
            server_name_val = "Unknown Server"


    chat_ids_to_notify_list = []
    async with SessionFactory() as session:
        all_subscriber_ids = await get_all_subscribers_ids(session)
        for chat_id_val in all_subscriber_ids:
            if await should_notify_user(chat_id_val, user_username_val, event_type, session):
                chat_ids_to_notify_list.append(chat_id_val)

    if not chat_ids_to_notify_list:
        logger.info(f"No subscribers to notify for {event_type} of user {user_username_val} ({user_id_val}).")
        return

    def text_generator_func(lang_code: str) -> str:
        key = JOIN_NOTIFICATION if event_type == NOTIFICATION_EVENT_JOIN else LEAVE_NOTIFICATION
        return get_text(key, lang_code, user_nickname=html.quote(user_nickname_val), server_name=html.quote(server_name_val))

    await send_telegram_messages_to_list(
        bot_token_to_use=app_config["TG_EVENT_TOKEN"], # Notifications go via event bot
        chat_ids=chat_ids_to_notify_list,
        text_generator=text_generator_func,
        reply_markup_generator=_generate_join_leave_markup,
        tt_user_username_for_markup=user_username_val,
        tt_user_nickname_for_markup=user_nickname_val, # Pass the TT user's nickname for the button
        tt_instance_for_check=tt_instance # For silent notification check
    )
    logger.info(f"Prepared {event_type} notification for {user_username_val} ({user_id_val}) to {len(chat_ids_to_notify_list)} subscribers.")
