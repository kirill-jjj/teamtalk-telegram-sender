"""Service for advanced notification logic like NOON."""

import logging

from pytalk.user import User as TeamTalkUser

from bot.core.enums import NotificationType
from bot.database.engine import AsyncSessionFactoryType
from bot.database.models import UserSettings
from bot.database.types import MuteListMode
from bot.database.uow import SqlModelUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.schemas import RecipientDTO

logger = logging.getLogger(__name__)


def is_user_subject_to_noon_check(user_settings: UserSettings | None) -> bool:
    """Checks if a user has NOON enabled and confirmed."""
    if not user_settings:
        return False
    return user_settings.not_on_online_enabled and user_settings.not_on_online_confirmed


def should_send_silently(
    chat_id: int,
    cache: CacheService,
    online_users_cache: dict[int, TeamTalkUser] | None,
) -> bool:
    """Determmunes if a message to a chat_id should be sent silently based on NOON."""
    recipient_settings = cache.get_user_settings(chat_id)
    if not is_user_subject_to_noon_check(recipient_settings):
        return False

    if online_users_cache and is_linked_user_online(chat_id, cache, online_users_cache):
        logger.debug(
            "Message to %s will be silent: linked user is online and NOON is enabled.",
            chat_id,
        )
        return True

    return False


def is_linked_user_online(
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
        tt_user_obj.username == linked_tt_username
        for tt_user_obj in online_users_cache.values()
    )


def is_muted(
    username: str, mute_list_mode: MuteListMode, muted_usernames_set: set[str]
) -> bool:
    """Determines if a username is muted based on user settings."""
    is_in_set = username in muted_usernames_set
    if mute_list_mode == MuteListMode.whitelist:
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
        self, username_to_check: str, event_type: NotificationType
    ) -> list[RecipientDTO]:
        """Finds all users who should receive a notification for a given event."""
        subscriber_ids = list(self.cache.get_all_subscriber_ids())
        if not subscriber_ids:
            return []

        async with SqlModelUnitOfWork(self.session_factory) as uow:
            raw_results = await uow.users.get_notification_recipients(
                subscriber_ids, username_to_check, event_type
            )
            return [
                RecipientDTO(telegram_id=telegram_id, language_code=lang_code)
                for telegram_id, lang_code in raw_results
            ]
