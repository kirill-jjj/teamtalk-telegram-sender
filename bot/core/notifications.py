import logging
from datetime import datetime, timedelta
from aiogram import html

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser

from bot.config import app_config
from bot.localization import get_text
from bot.database.crud import get_all_subscribers_ids
from bot.database.engine import SessionFactory
from bot.core.user_settings import get_or_create_user_settings
from bot.telegram_bot.utils import send_telegram_messages_to_list
from bot.constants import (
    NOTIFICATION_EVENT_JOIN,
    NOTIFICATION_EVENT_LEAVE,
    INITIAL_LOGIN_IGNORE_DELAY_SECONDS
)
from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.core.utils import get_effective_server_name, get_tt_user_display_name

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _should_ignore_initial_event(event_type: str, username: str, user_id: int) -> bool:
    """Checks if the event should be ignored due to recent bot login."""
    current_login_complete_time = tt_bot_module.login_complete_time
    reason_for_ignore = ""

    if current_login_complete_time is None:
        reason_for_ignore = "bot still initializing/reconnecting"
    elif datetime.utcnow() < current_login_complete_time + timedelta(seconds=INITIAL_LOGIN_IGNORE_DELAY_SECONDS):
        reason_for_ignore = "bot login too recent"
    else:
        return False # Not ignoring

    if event_type == NOTIFICATION_EVENT_JOIN: # Log only for join events to reduce noise for leave events during init
        logger.debug(f"Ignoring potential initial sync {event_type} for {username} ({user_id}). Reason: {reason_for_ignore}.")
    return True # Ignoring the event


def _is_user_globally_ignored(username: str) -> bool:
    """Checks if the user is in the global ignore list from the config."""
    global_ignore_str = app_config.get("GLOBAL_IGNORE_USERNAMES", "")
    if not global_ignore_str:
        return False

    ignored_set = {name.strip() for name in global_ignore_str.split(',') if name.strip()}
    return username in ignored_set


async def _get_recipients_for_notification(username: str, event_type: str) -> list[int]:
    """
    Gets a list of Telegram user IDs who should receive a notification for a given event.
    """
    recipients = []
    async with SessionFactory() as session:
        all_subscriber_ids = await get_all_subscribers_ids(session)
        for chat_id in all_subscriber_ids:
            if await should_notify_user(chat_id, username, event_type, session):
                recipients.append(chat_id)
    return recipients


async def should_notify_user(
    telegram_id: int,
    tt_user_username: str, 
    event_type: str, 
    session 
) -> bool:
    user_specific_settings = await get_or_create_user_settings(telegram_id, session)

    notification_pref = user_specific_settings.notification_settings
    mute_all_flag = user_specific_settings.mute_all_flag
    muted_users = user_specific_settings.muted_users_set

    from bot.database.models import NotificationSetting as NotificationSettingEnum
    if notification_pref == NotificationSettingEnum.NONE: return False
    if event_type == NOTIFICATION_EVENT_JOIN and notification_pref == NotificationSettingEnum.JOIN_OFF: return False
    if event_type == NOTIFICATION_EVENT_LEAVE and notification_pref == NotificationSettingEnum.LEAVE_OFF: return False

    if mute_all_flag:
        return tt_user_username in muted_users
    else:
        return tt_user_username not in muted_users


async def send_join_leave_notification_logic(
    event_type: str,
    tt_user: TeamTalkUser,
    tt_instance: TeamTalkInstance # Make sure TeamTalkInstance is the correct type from tt_instance_manager or pytalk
):
    user_nickname = get_tt_user_display_name(tt_user, "en") # For logging and display
    user_username = ttstr(tt_user.username) # Assuming ttstr is available (e.g. pytalk.instance.sdk.ttstr)
    user_id = tt_user.id

    if not user_username: # Check if username is empty or None
        logger.warning(f"User {event_type} with empty username (Nickname: {user_nickname}, ID: {user_id}). Skipping.")
        return

    # Call the new helper functions
    if _should_ignore_initial_event(event_type, user_username, user_id):
        return

    if _is_user_globally_ignored(user_username):
        logger.debug(f"User {user_username} is globally ignored. Skipping {event_type} notification.")
        return

    recipients = await _get_recipients_for_notification(user_username, event_type)

    if not recipients:
        logger.debug(f"No recipients found for {event_type} event for user {user_username}.")
        return

    logger.info(f"Notifications for {event_type} of {user_username} will be sent to {len(recipients)} users.")

    server_name = get_effective_server_name(tt_instance)

    def text_generator(lang_code: str) -> str:
        # Assuming NOTIFICATION_EVENT_JOIN is defined, e.g. from bot.constants
        key = "JOIN_NOTIFICATION" if event_type == NOTIFICATION_EVENT_JOIN else "LEAVE_NOTIFICATION"
        return get_text(key, lang_code, user_nickname=html.quote(user_nickname), server_name=html.quote(server_name))

    await send_telegram_messages_to_list(
        bot_token_to_use=app_config["TG_EVENT_TOKEN"], 
        chat_ids=recipients,
        text_generator=text_generator,
        tt_user_username_for_markup=user_username, # For potential markup buttons related to the user
        tt_user_nickname_for_markup=user_nickname, # For potential markup buttons
        tt_instance_for_check=tt_instance # For context in markup or other checks
    )
