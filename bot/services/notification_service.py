"""Service for advanced notification logic like NOON."""

import logging

import pytalk  # Required for ttstr
from pytalk.user import User as TeamTalkUser

from bot.models import UserSettings
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
