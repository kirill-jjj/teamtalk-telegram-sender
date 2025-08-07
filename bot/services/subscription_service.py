"""Service for managing user subscriptions."""

import logging

from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.models import OperationResult, SubscribedUser, UserSettings
from bot.services.cache_service import CacheService

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Service for managing user subscriptions."""

    def __init__(
        self,
        user_repo: UserRepository,
        subscriber_repo: SubscriberRepository,
        ban_repo: BanRepository,
        cache: CacheService,
    ) -> None:
        """Initializes the subscription service.

        Args:
            user_repo: The user repository.
            subscriber_repo: The subscriber repository.
            ban_repo: The ban repository.
            cache: The cache service.
        """
        self._user_repo = user_repo
        self._subscriber_repo = subscriber_repo
        self._ban_repo = ban_repo
        self._cache = cache

    async def create_subscription(self, user_settings: UserSettings, tt_username: str) -> bool:
        """Handles all DB and cache operations for a new subscription.

        Args:
            user_settings: The user's settings object.
            tt_username: The user's TeamTalk username.

        Returns:
            True if the subscription was created successfully, False otherwise.
        """
        telegram_id = user_settings.telegram_id
        subscriber = await self._subscriber_repo.get_by_id(telegram_id)
        if not subscriber:
            from bot.models import SubscribedUser

            new_subscriber = SubscribedUser(telegram_id=telegram_id)
            await self._subscriber_repo.add(new_subscriber)
            logger.info("User %s newly subscribed.", telegram_id)
            self._cache.add_subscriber(telegram_id)
        else:
            logger.info("User %s re-confirmed subscription.", telegram_id)

        user_settings.teamtalk_username = tt_username
        user_settings.not_on_online_confirmed = True
        await self._user_repo.save(user_settings)
        self._cache.update_user_settings(user_settings)
        logger.info(
            "Linked TT username '%s' and confirmed NOON for user %s.",
            tt_username,
            telegram_id,
        )
        return True

    async def delete_profile(self, telegram_id: int) -> bool:
        """Orchestrates the full deletion of a user's profile from DB and cache.

        Args:
            telegram_id: The Telegram ID of the user to delete.

        Returns:
            True if deletion was successful, False otherwise.
        """
        logger.info("Deleting full user profile for Telegram ID: %s", telegram_id)
        user_settings = await self._user_repo.get_by_id(telegram_id)
        if user_settings:
            await self._user_repo.delete(user_settings)

        subscriber = await self._subscriber_repo.get_by_id(telegram_id)
        if subscriber:
            await self._subscriber_repo.delete(subscriber)

        self._cache.remove_user_profile(telegram_id)
        logger.info(
            "Full user profile deletion process completed for Telegram ID: %s.",
            telegram_id,
        )
        return True

    async def link_tt_account(self, user_settings: UserSettings, tt_username: str) -> OperationResult:
        """Links a TeamTalk account to a subscriber.

        Args:
            user_settings: The user's settings object.
            tt_username: The TeamTalk username to link.

        Returns:
            An OperationResult indicating success or failure.
        """
        if await self._ban_repo.is_teamtalk_username_banned(tt_username):
            logger.warning(
                "Attempt to link banned TT username '%s' to user %s.",
                tt_username,
                user_settings.telegram_id,
            )
            return OperationResult(
                success=False,
                message_key="link_tt_account_error_banned",
                message_args={"tt_username": tt_username},
            )

        original_tt_username = user_settings.teamtalk_username
        user_settings.teamtalk_username = tt_username
        user_settings.not_on_online_confirmed = True
        await self._user_repo.save(user_settings)
        self._cache.update_user_settings(user_settings)
        logger.info(
            "Admin linked TT username '%s' for user %s.",
            tt_username,
            user_settings.telegram_id,
        )

        is_relink = bool(original_tt_username and original_tt_username != tt_username)
        message_key = "link_tt_account_success_relinked" if is_relink else "link_tt_account_success_linked"
        return OperationResult(
            success=True,
            message_key=message_key,
            message_args={
                "new_tt_username": tt_username,
                "original_tt_username": original_tt_username or "",
            },
            user_settings=user_settings,
        )
