"""Service for advanced notification logic like NOON."""

import logging

from pytalk.user import User as TeamTalkUser

from bot.core.enums import NotificationType
from bot.database.models import UserSettings
from bot.database.types import MuteListMode
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.schemas import RecipientDTO

logger = logging.getLogger(__name__)


class NotificationRecipientService:
    """A service to determine who should receive notifications."""

    def __init__(self, cache: CacheService) -> None:
        """Initializes the NotificationRecipientService."""
        self.cache = cache

    async def find_recipients(
        self, uow: IUnitOfWork, username_to_check: str, event_type: NotificationType
    ) -> list[RecipientDTO]:
        """Finds all users who should receive a notification for a given event."""
        subscriber_ids = list(self.cache.get_all_subscriber_ids())
        if not subscriber_ids:
            return []

        raw_results = await uow.users.get_notification_recipients(
            subscriber_ids, username_to_check, event_type
        )
        return [
            RecipientDTO(telegram_id=telegram_id, language_code=lang_code)
            for telegram_id, lang_code in raw_results
        ]

    @staticmethod
    def is_user_subject_to_noon_check(
        user_settings: UserSettings | None,
    ) -> bool:
        """Checks if a user has NOON enabled and confirmed."""
        if not user_settings:
            return False
        return (
            user_settings.not_on_online_enabled
            and user_settings.not_on_online_confirmed
        )

    def should_send_silently(
        self,
        chat_id: int,
        online_users_cache: dict[int, TeamTalkUser] | None,
    ) -> bool:
        """Determines if a message should be sent silently based on NOON settings."""
        recipient_settings = self.cache.get_user_settings(chat_id)
        if not NotificationRecipientService.is_user_subject_to_noon_check(
            recipient_settings
        ):
            return False

        if online_users_cache and self.is_linked_user_online(
            chat_id, online_users_cache
        ):
            logger.debug(
                "Message to %s will be silent: linked user is online, NOON enabled.",
                chat_id,
            )
            return True

        return False

    def is_linked_user_online(
        self,
        telegram_id: int,
        online_users_cache: dict[int, TeamTalkUser],
    ) -> bool:
        """Checks if the TeamTalk user linked to the given telegram_id is online."""
        user_settings = self.cache.get_user_settings(telegram_id)
        if not user_settings or not user_settings.teamtalk_username:
            return False

        linked_tt_username = user_settings.teamtalk_username
        return any(
            tt_user_obj.username == linked_tt_username
            for tt_user_obj in online_users_cache.values()
        )

    @staticmethod
    def is_muted(
        username: str, mute_list_mode: MuteListMode, muted_usernames_set: set[str]
    ) -> bool:
        """Determines if a username is muted based on user settings."""
        is_in_set = username in muted_usernames_set
        if mute_list_mode == MuteListMode.whitelist:
            return not is_in_set  # In whitelist, not in set -> muted
        return is_in_set  # In blacklist, in set -> muted
