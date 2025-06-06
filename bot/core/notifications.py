import logging
from datetime import datetime, timedelta
from aiogram import html
from aiogram.types import InlineKeyboardMarkup

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser # Убедитесь, что это правильный User

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
# Import teamtalk_bot.bot_instance carefully
from bot.teamtalk_bot import bot_instance as tt_bot_module
from bot.core.utils import get_effective_server_name, get_tt_user_display_name

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr # Убедитесь, что sdk здесь доступен или импортируйте правильно


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

    try:
        from bot.database.models import NotificationSetting as NotificationSettingEnum
        if notification_pref == NotificationSettingEnum.NONE: return False
        if event_type == NOTIFICATION_EVENT_JOIN and notification_pref == NotificationSettingEnum.JOIN_OFF: return False
        if event_type == NOTIFICATION_EVENT_LEAVE and notification_pref == NotificationSettingEnum.LEAVE_OFF: return False
    except ImportError:
        logger.error("Could not import NotificationSetting enum for should_notify_user checks. String comparison fallback might be unreliable.")
        # Fallback, если enum не импортируется (менее надежно)
        if str(notification_pref.value) == "none": return False # Сравнение со строковым значением enum
        if event_type == NOTIFICATION_EVENT_JOIN and str(notification_pref.value) == "join_off": return False
        if event_type == NOTIFICATION_EVENT_LEAVE and str(notification_pref.value) == "leave_off": return False


    if mute_all_flag:
        return tt_user_username in muted_users
    else:
        return tt_user_username not in muted_users


def _generate_join_leave_markup(
    tt_user_username: str,
    tt_user_nickname: str, 
    lang_code: str,
    recipient_tg_id: int 
) -> InlineKeyboardMarkup | None:
    # The "Toggle ignore status" button is removed as per centralization of mute management.
    # If other buttons were to be added to join/leave notifications in the future,
    # they would be constructed here. For now, no buttons are shown.
    return None


async def send_join_leave_notification_logic(
    event_type: str,
    tt_user: TeamTalkUser,
    tt_instance: TeamTalkInstance
):
    logger.info(f"--- send_join_leave_notification_logic started for event: {event_type}, user: {ttstr(tt_user.username)} ---")

    # Получаем актуальное значение login_complete_time из модуля bot_instance
    current_login_complete_time = tt_bot_module.login_complete_time
    reason_for_ignore = ""

    if current_login_complete_time is None:
        reason_for_ignore = "bot still initializing/reconnecting"
    elif datetime.utcnow() < current_login_complete_time + timedelta(seconds=INITIAL_LOGIN_IGNORE_DELAY_SECONDS):
        reason_for_ignore = "bot login too recent"

    if reason_for_ignore:
        if event_type == NOTIFICATION_EVENT_JOIN:
             logger.debug(f"Ignoring potential initial sync {event_type} for {ttstr(tt_user.username)} ({tt_user.id}). Reason: {reason_for_ignore}.")
        logger.info(f"--- send_join_leave_notification_logic finished: Ignored. Reason: {reason_for_ignore} ---")
        return

    user_nickname_val = get_tt_user_display_name(tt_user, "en") # Using "en" as per original logic for this specific var
    user_username_val = ttstr(tt_user.username) # Still needed for specific checks like global ignore
    user_id_val = tt_user.id

    global_ignore_usernames_str = app_config.get("GLOBAL_IGNORE_USERNAMES", "")
    globally_ignored_usernames_set = set()
    if global_ignore_usernames_str:
        globally_ignored_usernames_set = {name.strip() for name in global_ignore_usernames_str.split(',') if name.strip()}

    if not user_username_val:
        logger.warning(f"User {event_type} with empty username (Nickname: {user_nickname_val}, ID: {user_id_val}). Skipping notification.")
        logger.info(f"--- send_join_leave_notification_logic finished: Empty username ---")
        return

    if user_username_val in globally_ignored_usernames_set:
        logger.info(f"User {user_username_val} is in the global ignore list. Skipping {event_type} notification.")
        logger.info(f"--- send_join_leave_notification_logic finished: User globally ignored ---")
        return

    server_name_val = get_effective_server_name(tt_instance)

    chat_ids_to_notify_list = []
    async with SessionFactory() as session:
        all_subscriber_ids = await get_all_subscribers_ids(session)
        logger.debug(f"Subscribers to check for notification: {all_subscriber_ids}")

        if not all_subscriber_ids:
            logger.info("No subscribers found in the database.")
        
        logger.info(f"Processing {event_type} notifications for TeamTalk user {user_username_val}. Checking {len(all_subscriber_ids)} subscribed Telegram users.")
        for chat_id_val in all_subscriber_ids:
            user_specific_settings_for_log = await get_or_create_user_settings(chat_id_val, session)
            # Используем .value для enum, если он доступен, иначе пытаемся привести к строке
            notification_pref_value = "N/A"
            if hasattr(user_specific_settings_for_log.notification_settings, 'value'):
                notification_pref_value = user_specific_settings_for_log.notification_settings.value
            elif user_specific_settings_for_log.notification_settings is not None:
                notification_pref_value = str(user_specific_settings_for_log.notification_settings)

            logger.debug(f"Checking notification for TG_ID {chat_id_val}. Settings: NotifyPref={notification_pref_value}, MuteAll={user_specific_settings_for_log.mute_all_flag}, MutedUsers={user_specific_settings_for_log.muted_users_set}. Event TT User: {user_username_val}")

            should_notify_result = await should_notify_user(chat_id_val, user_username_val, event_type, session)
            logger.debug(f"Result of should_notify_user for TG_ID {chat_id_val}: {should_notify_result}")

            if should_notify_result:
                chat_ids_to_notify_list.append(chat_id_val)
                logger.debug(f"TG_ID {chat_id_val} WILL be notified for {user_username_val}.")
            else:
                logger.debug(f"TG_ID {chat_id_val} WILL NOT be notified for {user_username_val}.")

    if chat_ids_to_notify_list:
        logger.info(f"Notifications for {event_type} of {user_username_val} will be sent to {len(chat_ids_to_notify_list)} Telegram users.")
    if not chat_ids_to_notify_list:
        return

    def text_generator_func(lang_code: str) -> str:
        key_str = "JOIN_NOTIFICATION" if event_type == NOTIFICATION_EVENT_JOIN else "LEAVE_NOTIFICATION"
        return get_text(key_str, lang_code, user_nickname=html.quote(user_nickname_val), server_name=html.quote(server_name_val))

    await send_telegram_messages_to_list(
        bot_token_to_use=app_config["TG_EVENT_TOKEN"], 
        chat_ids=chat_ids_to_notify_list,
        text_generator=text_generator_func,
        reply_markup_generator=_generate_join_leave_markup,
        tt_user_username_for_markup=user_username_val,
        tt_user_nickname_for_markup=user_nickname_val, 
        tt_instance_for_check=tt_instance 
    )
