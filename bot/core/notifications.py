"""Handles the logic for sending notifications based on TeamTalk events."""

from collections.abc import Callable
from datetime import datetime, timedelta
import gettext
from html import escape
import logging
from typing import TYPE_CHECKING, Any

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser
from sqlalchemy import and_, or_
from sqlmodel import select

from bot.constants import INITIAL_LOGIN_IGNORE_DELAY_SECONDS, NOTIFICATION_EVENT_JOIN, NOTIFICATION_EVENT_LEAVE
from bot.core.utils import get_effective_server_name, get_tt_user_display_name
from bot.models import MutedUser, MuteListMode, NotificationSetting, UserSettings
from bot.telegram_bot.utils import send_telegram_messages_to_list

# TYPE_CHECKING block for imports ONLY used for type hinting that would cause circular deps
if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker  # For DbSessionFactory alias if used as a type

    # Using a more specific alias to avoid conflict if DbSessionFactory is used elsewhere
    from bot.database.engine import SessionFactory as DbEngineSessionFactoryType
    from bot.services_container import Services

    DbSessionFactory = sessionmaker  # Alias for SessionFactory from sqlalchemy.orm for type hints in this module


logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _should_ignore_initial_event(
    event_type: str, username: str, user_id: int, login_complete_time: datetime | None
) -> bool:
    reason_for_ignore = ""
    if login_complete_time is None:
        reason_for_ignore = "bot still initializing/reconnecting"
    elif datetime.utcnow() < login_complete_time + timedelta(seconds=INITIAL_LOGIN_IGNORE_DELAY_SECONDS):
        reason_for_ignore = "bot login too recent"
    else:
        return False
    if event_type == NOTIFICATION_EVENT_JOIN:
        logger.debug(
            "Ignoring potential initial sync %s for %s (%s). Reason: %s.",
            event_type,
            username,
            user_id,
            reason_for_ignore,
        )
    return True


def _is_user_globally_ignored(username: str, app_cfg: Any) -> bool:  # Pass app_cfg
    global_ignore_str = app_cfg.GLOBAL_IGNORE_USERNAMES or ""
    if not global_ignore_str:
        return False
    ignored_set = {name.strip() for name in global_ignore_str.split(",") if name.strip()}
    return username in ignored_set


async def _get_recipients_for_notification(
    username_to_check: str,
    event_type: str,
    session_factory: "DbEngineSessionFactoryType",  # Use renamed alias
    subscribed_users_cache: set[int],
) -> list[int]:
    subscriber_ids = list(subscribed_users_cache)
    if not subscriber_ids:
        return []

    async with session_factory() as session:
        filters = [
            UserSettings.telegram_id.in_(subscriber_ids),
            UserSettings.notification_settings != NotificationSetting.NONE,
        ]
        if event_type == NOTIFICATION_EVENT_JOIN:
            filters.append(UserSettings.notification_settings != NotificationSetting.JOIN_OFF)
        elif event_type == NOTIFICATION_EVENT_LEAVE:
            filters.append(UserSettings.notification_settings != NotificationSetting.LEAVE_OFF)

        user_is_in_list_subquery = (
            select(MutedUser.id)
            .where(
                and_(
                    MutedUser.user_settings_telegram_id == UserSettings.telegram_id,
                    MutedUser.muted_teamtalk_username == username_to_check,
                )
            )
            .exists()
        )
        mute_logic = or_(
            and_(UserSettings.mute_list_mode == MuteListMode.blacklist, ~user_is_in_list_subquery),
            and_(UserSettings.mute_list_mode == MuteListMode.whitelist, user_is_in_list_subquery),
        )
        filters.append(mute_logic)
        stmt = select(UserSettings.telegram_id).where(and_(*filters))
        result = await session.execute(stmt)
        return result.scalars().all()


def _generate_join_leave_notification_text(
    tt_user: TeamTalkUser,
    server_name: str,
    event_type: str,
    lang_code: str,
    get_translator_func: Callable[[str | None], gettext.GNUTranslations],  # Changed signature
) -> str:
    recipient_translator = get_translator_func(lang_code)  # Use passed function
    _ = recipient_translator_func = recipient_translator.gettext
    localized_user_nickname = get_tt_user_display_name(tt_user, recipient_translator_func)
    if event_type == NOTIFICATION_EVENT_JOIN:
        notification_template = _("User {user_nickname} joined server {server_name}")
    else:
        notification_template = _("User {user_nickname} left server {server_name}")
    return notification_template.format(user_nickname=escape(localized_user_nickname), server_name=escape(server_name))


async def send_join_leave_notification_logic(
    event_type: str,
    tt_user: TeamTalkUser,
    tt_instance: TeamTalkInstance,
    login_complete_time: datetime | None,
    online_users_cache_for_instance: dict[int, "pytalk.user.User"],
    services: "Services",
):
    """Core logic for sending join/leave notifications.

    This function determines who should receive a notification based on their settings,
    the event type (join/leave), and the NOON (Not On Online) feature.

    Args:
        event_type: The type of event ("join" or "leave").
        tt_user: The TeamTalkUser object for the user who triggered the event.
        tt_instance: The TeamTalkInstance where the event occurred.
        login_complete_time: Timestamp when the bot's login to this instance was finalized.
        online_users_cache_for_instance: Cache of online users for the specific TT instance.
        services: The application's services container.
    """
    default_lang_for_markup_and_log = services.config.general.default_lang
    _log_markup_translator = services.get_translator(default_lang_for_markup_and_log).gettext
    user_nickname = get_tt_user_display_name(tt_user, _log_markup_translator)

    user_username = ttstr(tt_user.username)
    user_id = tt_user.id

    if not user_username:
        logger.warning(
            "User %s with empty username (Nickname: %s, ID: %s) on server %s. Skipping.",
            event_type,
            user_nickname,
            user_id,
            tt_instance.server_info.host,
        )
        return

    if _should_ignore_initial_event(event_type, user_username, user_id, login_complete_time):
        return

    if _is_user_globally_ignored(user_username, services.config):
        logger.debug(
            "User %s is globally ignored on server %s. Skipping %s notification.",
            user_username,
            tt_instance.server_info.host,
            event_type,
        )
        return

    recipients = await _get_recipients_for_notification(
        user_username, event_type, services.session_factory, services.subscribed_users_cache
    )

    if not recipients:
        logger.debug(
            "No recipients found for %s event for user %s on server %s.",
            event_type,
            user_username,
            tt_instance.server_info.host,
        )
        return

    logger.info(
        "Notifications for %s of %s on server %s will be sent to %s initial recipients.",
        event_type,
        user_username,
        tt_instance.server_info.host,
        len(recipients),
    )
    server_name = get_effective_server_name(tt_instance, _log_markup_translator, services.config)

    final_recipients = []

    for tg_user_id in recipients:
        user_specific_settings = services.user_settings_cache.get(tg_user_id)
        if not user_specific_settings:
            logger.warning(
                "User settings not found in cache for recipient %s during final NOON check. Skipping NOON for them.",
                tg_user_id,
            )
            final_recipients.append(tg_user_id)
            continue

        if user_specific_settings.not_on_online_enabled and tt_user.id != tt_instance.getMyUserID():
            is_event_user_tt_admin = user_username == services.config.ADMIN_USERNAME

            if not is_event_user_tt_admin:
                other_users_online_in_instance = False
                for online_user_id_in_instance in online_users_cache_for_instance:
                    if (
                        online_user_id_in_instance != tt_instance.getMyUserID()
                        and online_user_id_in_instance != tt_user.id
                    ):
                        other_users_online_in_instance = True
                        break
                if not other_users_online_in_instance:
                    logger.debug(
                        "NOON: User %s is the only one online (besides bot) for TG user %s "
                        "on server %s. Skipping notification for this recipient.",
                        user_nickname,
                        tg_user_id,
                        tt_instance.server_info.host,
                    )
                    continue
        final_recipients.append(tg_user_id)

    if not final_recipients:
        logger.info(
            "No recipients left after NOON filtering for %s of %s on server %s.",
            event_type,
            user_username,
            tt_instance.server_info.host,
        )
        return

    logger.info(
        "Final notifications for %s of %s on server %s will be sent to %s users.",
        event_type,
        user_username,
        tt_instance.server_info.host,
        len(final_recipients),
    )

    await send_telegram_messages_to_list(
        bot_instance_to_use=services.bot_event,
        chat_ids=final_recipients,
        text_generator=lambda lang_code: _generate_join_leave_notification_text(
            tt_user, server_name, event_type, lang_code, get_translator_func=services.get_translator
        ),
        services=services,
        online_users_cache_for_instance=online_users_cache_for_instance,
    )
