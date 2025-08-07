"""Handles the logic for sending notifications based on TeamTalk events."""

from collections.abc import Callable
import datetime as dt
from datetime import datetime, timedelta
import gettext
from gettext import NullTranslations
from html import escape
import logging
from typing import cast

from aiogram import Bot
import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser
from sqlalchemy import and_, or_
from sqlmodel import select

from bot.config import Settings
from bot.constants import (
    INITIAL_LOGIN_IGNORE_DELAY_SECONDS,
    NOTIFICATION_EVENT_JOIN,
    NOTIFICATION_EVENT_LEAVE,
)
from bot.database.engine import AsyncSessionFactoryType
from bot.models import MutedUser, MuteListMode, NotificationSetting, UserSettings
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.utils import get_effective_server_name, get_tt_user_display_name
from bot.telegram_bot.utils import broadcast_to_users

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _should_ignore_initial_event(
    event_type: str, username: str, user_id: int, login_complete_time: datetime | None
) -> bool:
    reason_for_ignore = ""
    if login_complete_time is None:
        reason_for_ignore = "bot still initializing/reconnecting"
    elif datetime.now(dt.UTC) < login_complete_time + timedelta(
        seconds=INITIAL_LOGIN_IGNORE_DELAY_SECONDS
    ):
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


def _is_user_globally_ignored(username: str, app_cfg: "Settings") -> bool:
    global_ignore_list = app_cfg.teamtalk.global_ignore_usernames
    if not global_ignore_list:
        return False
    # Usernames in the list are expected to be already stripped and valid
    return username in global_ignore_list


async def _get_recipients_for_notification(
    username_to_check: str,
    event_type: str,
    session_factory: AsyncSessionFactoryType,
    cache: CacheService,
) -> list[tuple[int, str | None]]:
    subscriber_ids = list(cache.get_all_subscriber_ids())
    if not subscriber_ids:
        return []

    async with session_factory() as session:
        # Now selecting telegram_id and language_code along with NOON flags
        stmt = select(
            UserSettings.telegram_id,
            UserSettings.not_on_online_enabled,
            UserSettings.not_on_online_confirmed,
            UserSettings.language_code,
        )

        # The rest of the query remains the same
        stmt = stmt.join(
            MutedUser,
            and_(
                UserSettings.telegram_id == MutedUser.user_settings_telegram_id,
                MutedUser.muted_teamtalk_username == username_to_check,
            ),
            isouter=True,
        )

        filters = [
            UserSettings.telegram_id.in_(subscriber_ids),  # type: ignore[attr-defined]
            UserSettings.notification_settings != NotificationSetting.NONE,
        ]
        if event_type == NOTIFICATION_EVENT_JOIN:
            filters.append(
                UserSettings.notification_settings != NotificationSetting.JOIN_OFF
            )
        elif event_type == NOTIFICATION_EVENT_LEAVE:
            filters.append(
                UserSettings.notification_settings != NotificationSetting.LEAVE_OFF
            )

        mute_logic = or_(
            and_(
                UserSettings.mute_list_mode == MuteListMode.blacklist.value,
                MutedUser.id.is_(None),
            ),
            and_(
                UserSettings.mute_list_mode == MuteListMode.whitelist.value,
                MutedUser.id.is_not(None),
            ),
        )
        filters.append(mute_logic)  # type: ignore[arg-type]

        stmt = stmt.where(and_(*filters))

        result = await session.execute(stmt)
        # The result now includes the language code
        recipients_data = cast(list[tuple[int, bool, bool, str | None]], result.all())

    # We no longer filter here. Instead, we pass all recipients to the sender,
    # which will decide whether to send a notification silently based on NOON settings.
    # The data is transformed from (id, noon_enabled, noon_confirmed, lang)
    # to (id, lang).
    return [(tg_id, lang_code) for tg_id, _, _, lang_code in recipients_data]


def _generate_join_leave_notification_text(
    tt_user: TeamTalkUser,
    server_name: str,
    event_type: str,
    lang_code: str,
    get_translator_func: Callable[[str | None], gettext.NullTranslations],
) -> str:
    recipient_translator = get_translator_func(lang_code)
    # Pass the full translator object to get_tt_user_display_name
    localized_user_nickname = get_tt_user_display_name(tt_user, recipient_translator)

    _ = recipient_translator.gettext  # Keep this for the template strings below
    if event_type == NOTIFICATION_EVENT_JOIN:
        notification_template = _("{user_nickname} joined server {server_name}")
    else:
        notification_template = _("{user_nickname} left server {server_name}")
    return notification_template.format(
        user_nickname=escape(localized_user_nickname), server_name=escape(server_name)
    )


async def send_join_leave_notification(
    event_type: str,
    tt_user: TeamTalkUser,
    tt_instance: TeamTalkInstance,
    login_complete_time: datetime | None,
    online_users_cache_for_instance: dict[int, "pytalk.user.User"],
    settings: Settings,
    session_factory: AsyncSessionFactoryType,
    cache: CacheService,
    translator_factory: Callable[[str], NullTranslations],
    bot: Bot,
) -> None:
    """Core logic for sending join/leave notifications."""
    default_lang_for_markup_and_log = settings.general.default_lang
    default_lang_translator_obj = translator_factory(default_lang_for_markup_and_log)
    user_nickname = get_tt_user_display_name(tt_user, default_lang_translator_obj)

    user_username = ttstr(tt_user.username)
    user_id = tt_user.id

    if not user_username:
        logger.warning(
            "User %s with empty username (Nickname: %s, ID: %s) on server %s. "
            "Skipping.",
            event_type,
            user_nickname,
            user_id,
            tt_instance.server_info.host,
        )
        return

    if _should_ignore_initial_event(
        event_type, user_username, user_id, login_complete_time
    ):
        return

    if _is_user_globally_ignored(user_username, settings):
        logger.debug(
            "User %s is globally ignored on server %s. Skipping %s notification.",
            user_username,
            tt_instance.server_info.host,
            event_type,
        )
        return

    final_recipients = await _get_recipients_for_notification(
        username_to_check=user_username,
        event_type=event_type,
        session_factory=session_factory,
        cache=cache,
    )

    if not final_recipients:
        logger.debug(
            "No recipients found for %s event for user %s on server %s "
            "after all filtering.",
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

    server_name = get_effective_server_name(
        tt_instance, default_lang_translator_obj, settings
    )
    # The list of recipients now includes language codes, so we pass it directly
    await broadcast_to_users(
        bot_instance_to_use=bot,
        recipients_with_lang=final_recipients,
        text_generator=lambda lang_code: _generate_join_leave_notification_text(
            tt_user,
            server_name,
            event_type,
            lang_code,
            get_translator_func=translator_factory,
        ),
        cache=cache,
        session_factory=session_factory,
        online_users_cache_for_instance=online_users_cache_for_instance,
    )
