# mypy: ignore-errors
"""Service for advanced notification logic like NOON."""

import logging
from typing import cast

import pytalk  # Required for ttstr
from pytalk.user import User as TeamTalkUser
from sqlalchemy import and_, or_
from sqlmodel import select

from bot.constants import NOTIFICATION_EVENT_JOIN, NOTIFICATION_EVENT_LEAVE
from bot.database.engine import AsyncSessionFactoryType
from bot.models import MutedUser, MuteListMode, NotificationSetting, UserSettings
from bot.services.cache_service import CacheService

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def is_user_subject_to_noon_check(user_settings: UserSettings | None) -> bool:
    """Checks if a user has NOON enabled and confirmed."""
    if not user_settings:
        return False
    return user_settings.not_on_online_enabled and user_settings.not_on_online_confirmed


async def is_linked_user_online(
    telegram_id: int,
    cache: CacheService,
    online_users_cache: dict[int, TeamTalkUser],
) -> bool:
    """Checks if the TeamTalk user linked to the given telegram_id is online."""
    user_settings = cache.get_user_settings(telegram_id)
    if not user_settings or not user_settings.teamtalk_username:
        return False

    linked_tt_username = user_settings.teamtalk_username
    return any(
        ttstr(tt_user_obj.username) == linked_tt_username
        for tt_user_obj in online_users_cache.values()
    )


def is_username_effectively_muted(
    username: str, user_settings: UserSettings, muted_usernames_set: set[str]
) -> bool:
    """Determines if a username is effectively muted based on user settings."""
    is_in_set = username in muted_usernames_set
    if user_settings.mute_list_mode == MuteListMode.whitelist:
        return not is_in_set  # In whitelist, not in set -> muted
    return is_in_set  # In blacklist, in set -> muted


class NotificationRecipientService:
    """A service to determine who should receive notifications."""

    def __init__(
        self, session_factory: AsyncSessionFactoryType, cache: CacheService
    ) -> None:
        """Initializes the NotificationRecipientService."""
        self.session_factory = session_factory
        self.cache = cache

    async def find_recipients(
        self, username_to_check: str, event_type: str
    ) -> list[tuple[int, str | None]]:
        """Finds all users who should receive a notification for a given event."""
        subscriber_ids = list(self.cache.get_all_subscriber_ids())
        if not subscriber_ids:
            return []

        async with self.session_factory() as session:
            stmt = select(
                UserSettings.telegram_id,
                UserSettings.language_code,
            ).join(
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
            return cast("list[tuple[int, str | None]]", result.all())
