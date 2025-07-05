import logging
from datetime import datetime, timedelta
from aiogram import Bot as AiogramBot, html # Renamed Bot
from typing import TYPE_CHECKING, Optional, Set, Any # Added Set, Any

from sqlalchemy import and_, or_

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser
from sqlmodel import select

# from bot.config import app_config # Will be passed as app_config_instance
from bot.language import get_translator
# from bot.database.engine import SessionFactory # Will be passed as session_factory
# from bot.state import SUBSCRIBED_USERS_CACHE # Will be passed as subscribed_users_cache
from bot.models import UserSettings, MutedUser, NotificationSetting, MuteListMode
from bot.telegram_bot.utils import send_telegram_messages_to_list
# from bot.telegram_bot.bot_instances import tg_bot_event # Will be passed as bot (AiogramBot)
from bot.constants import (
    NOTIFICATION_EVENT_JOIN,
    NOTIFICATION_EVENT_LEAVE,
    INITIAL_LOGIN_IGNORE_DELAY_SECONDS
)
from bot.core.utils import get_effective_server_name, get_tt_user_display_name

if TYPE_CHECKING:
    from bot.database.engine import SessionFactory as DbSessionFactory


logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _should_ignore_initial_event(event_type: str, username: str, user_id: int, login_complete_time: datetime | None) -> bool:
    reason_for_ignore = ""
    if login_complete_time is None: reason_for_ignore = "bot still initializing/reconnecting"
    elif datetime.utcnow() < login_complete_time + timedelta(seconds=INITIAL_LOGIN_IGNORE_DELAY_SECONDS):
        reason_for_ignore = "bot login too recent"
    else: return False
    if event_type == NOTIFICATION_EVENT_JOIN:
        logger.debug(f"Ignoring potential initial sync {event_type} for {username} ({user_id}). Reason: {reason_for_ignore}.")
    return True


def _is_user_globally_ignored(username: str, app_cfg: Any) -> bool: # Pass app_cfg
    global_ignore_str = app_cfg.GLOBAL_IGNORE_USERNAMES or ""
    if not global_ignore_str: return False
    ignored_set = {name.strip() for name in global_ignore_str.split(',') if name.strip()}
    return username in ignored_set


async def _get_recipients_for_notification(
    username_to_check: str,
    event_type: str,
    session_factory: "DbSessionFactory", # Pass factory
    subscribed_users_cache: Set[int] # Pass cache
) -> list[int]:
    subscriber_ids = list(subscribed_users_cache) # Use passed cache
    if not subscriber_ids: return []

    async with session_factory() as session: # Use passed factory
        filters = [
            UserSettings.telegram_id.in_(subscriber_ids),
            UserSettings.notification_settings != NotificationSetting.NONE
        ]
        if event_type == NOTIFICATION_EVENT_JOIN: filters.append(UserSettings.notification_settings != NotificationSetting.JOIN_OFF)
        elif event_type == NOTIFICATION_EVENT_LEAVE: filters.append(UserSettings.notification_settings != NotificationSetting.LEAVE_OFF)

        user_is_in_list_subquery = select(MutedUser.id).where(
            and_(
                MutedUser.user_settings_telegram_id == UserSettings.telegram_id,
                MutedUser.muted_teamtalk_username == username_to_check
            )
        ).exists()
        mute_logic = or_(
            and_(UserSettings.mute_list_mode == MuteListMode.blacklist, ~user_is_in_list_subquery),
            and_(UserSettings.mute_list_mode == MuteListMode.whitelist, user_is_in_list_subquery)
        )
        filters.append(mute_logic)
        stmt = select(UserSettings.telegram_id).where(and_(*filters))
        result = await session.execute(stmt)
        return result.scalars().all()


def _generate_join_leave_notification_text( # No change needed here
    tt_user: TeamTalkUser, server_name: str, event_type: str, lang_code: str
) -> str:
    _ = recipient_translator_func = get_translator(lang_code).gettext
    localized_user_nickname = get_tt_user_display_name(tt_user, recipient_translator_func)
    notification_template = _("User {user_nickname} joined server {server_name}") if event_type == NOTIFICATION_EVENT_JOIN \
                            else _("User {user_nickname} left server {server_name}")
    return notification_template.format(user_nickname=html.quote(localized_user_nickname), server_name=html.quote(server_name))


async def send_join_leave_notification_logic(
    event_type: str,
    tt_user: TeamTalkUser,
    tt_instance: TeamTalkInstance,
    login_complete_time: datetime | None,
    bot: AiogramBot, # Parameter from Application
    session_factory: "DbSessionFactory", # Parameter from Application
    user_settings_cache: dict[int, UserSettings], # Parameter from Application
    subscribed_users_cache: Set[int], # Parameter from Application
    online_users_cache_for_instance: dict[int, "pytalk.user.User"], # Parameter from Application
    app_config_instance: Any # Parameter from Application
):
    default_lang_for_markup_and_log = app_config_instance.DEFAULT_LANG # Use passed app_config
    _log_markup_translator = get_translator(default_lang_for_markup_and_log).gettext
    user_nickname = get_tt_user_display_name(tt_user, _log_markup_translator)

    user_username = ttstr(tt_user.username)
    user_id = tt_user.id

    if not user_username:
        logger.warning(f"User {event_type} with empty username (Nickname: {user_nickname}, ID: {user_id}) on server {tt_instance.server_info.host}. Skipping.")
        return

    if _should_ignore_initial_event(event_type, user_username, user_id, login_complete_time):
        return

    if _is_user_globally_ignored(user_username, app_config_instance): # Pass app_config
        logger.debug(f"User {user_username} is globally ignored on server {tt_instance.server_info.host}. Skipping {event_type} notification.")
        return

    # Pass session_factory and subscribed_users_cache to _get_recipients_for_notification
    recipients = await _get_recipients_for_notification(user_username, event_type, session_factory, subscribed_users_cache)

    if not recipients:
        logger.debug(f"No recipients found for {event_type} event for user {user_username} on server {tt_instance.server_info.host}.")
        return

    logger.info(f"Notifications for {event_type} of {user_username} on server {tt_instance.server_info.host} will be sent to {len(recipients)} initial recipients.")
    server_name = get_effective_server_name(tt_instance, _log_markup_translator, app_config_instance)

    final_recipients = []
    # Prepare online usernames set for NOON check (if needed by send_telegram_messages_to_list or for pre-filtering)
    # This set is specific to the instance of the event.
    online_usernames_for_noon_check = {ttstr(u.username) for u in online_users_cache_for_instance.values()}

    for tg_user_id in recipients:
        user_specific_settings = user_settings_cache.get(tg_user_id)
        if not user_specific_settings: # Should have been fetched by _get_recipients_for_notification
            logger.warning(f"User settings not found in cache for recipient {tg_user_id} during final NOON check. Skipping NOON for them.")
            final_recipients.append(tg_user_id) # Add them if other checks passed
            continue

        # NOON (Not On Online) check per recipient
        if user_specific_settings.not_on_online_enabled and tt_user.id != tt_instance.getMyUserID():
            is_event_user_tt_admin = (app_config_instance.ADMIN_USERNAME == user_username)

            if not is_event_user_tt_admin: # Only apply NOON if the event user is NOT the configured TT admin
                other_users_online_in_instance = False
                for online_user_id_in_instance in online_users_cache_for_instance.keys():
                    if online_user_id_in_instance != tt_instance.getMyUserID() and online_user_id_in_instance != tt_user.id:
                        other_users_online_in_instance = True
                        break
                if not other_users_online_in_instance:
                    logger.debug(f"NOON: User {user_nickname} is the only one online (besides bot) for TG user {tg_user_id} on server {server_host}. Skipping notification for this recipient.")
                    continue # Skip this recipient
        final_recipients.append(tg_user_id)

    if not final_recipients:
        logger.info(f"No recipients left after NOON filtering for {event_type} of {user_username} on server {tt_instance.server_info.host}.")
        return

    logger.info(f"Final notifications for {event_type} of {user_username} on server {tt_instance.server_info.host} will be sent to {len(final_recipients)} users.")

    await send_telegram_messages_to_list(
        bot_instance_to_use=bot,
        chat_ids=final_recipients, # Use filtered list
        text_generator=lambda lang_code: _generate_join_leave_notification_text(
            tt_user, server_name, event_type, lang_code
        ),
        user_settings_cache=user_settings_cache, # This is app.user_settings_cache passed in
        app=app_config_instance, # app_config_instance is the 'app' Application object
        online_users_cache_for_instance=online_users_cache_for_instance
    )
