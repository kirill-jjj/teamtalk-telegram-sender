"""Service for managing user subscriptions."""

import logging

from bot.database.uow import IUnitOfWork
from bot.models import OperationResult, SubscribedUser, UserSettings
from bot.services.cache_service import CacheService

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Service for managing user subscriptions."""

    def __init__(self, uow: IUnitOfWork, cache: CacheService) -> None:
        """Initializes the subscription service.

        Args:
            uow: The unit of work.
            cache: The cache service.
        """
        self._uow = uow
        self._cache = cache

    async def create_subscription(
        self, user_settings: UserSettings, tt_username: str
    ) -> bool:
        """Handles all DB and cache operations for a new subscription."""
        telegram_id = user_settings.telegram_id
        async with self._uow:
            subscriber = await self._uow.subscribers.get_by_id(telegram_id)
            if not subscriber:
                new_subscriber = SubscribedUser(telegram_id=telegram_id)
                await self._uow.subscribers.add(new_subscriber)
                logger.info("User %s newly subscribed.", telegram_id)
                self._cache.add_subscriber(telegram_id)
            else:
                logger.info("User %s re-confirmed subscription.", telegram_id)

            user_settings.teamtalk_username = tt_username
            user_settings.not_on_online_confirmed = True
            await self._uow.users.save(user_settings)
            await self._uow.commit()

        self._cache.update_user_settings(user_settings)
        logger.info(
            "Linked TT username '%s' and confirmed NOON for user %s.",
            tt_username,
            telegram_id,
        )
        return True

    async def delete_profile(
        self, telegram_id: int, uow: IUnitOfWork | None = None
    ) -> bool:
        """Orchestrates the full deletion of a user's profile from DB and cache."""
        logger.info("Deleting full user profile for Telegram ID: %s", telegram_id)

        # Use the provided UoW or create a new one
        active_uow = uow or self._uow

        async with active_uow:
            user_settings = await active_uow.users.get_by_id(telegram_id)
            if user_settings:
                await active_uow.users.delete(user_settings)

            subscriber = await active_uow.subscribers.get_by_id(telegram_id)
            if subscriber:
                await active_uow.subscribers.delete(subscriber)

            if not uow:  # Only commit if we created the transaction
                await active_uow.commit()

        self._cache.remove_user_profile(telegram_id)
        logger.info(
            "Full user profile deletion process completed for Telegram ID: %s.",
            telegram_id,
        )
        return True

    async def link_tt_account(
        self, user_settings: UserSettings, tt_username: str
    ) -> OperationResult:
        """Links a TeamTalk account to a subscriber."""
        async with self._uow:
            if await self._uow.bans.is_teamtalk_username_banned(tt_username):
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
            await self._uow.users.save(user_settings)
            await self._uow.commit()

        self._cache.update_user_settings(user_settings)
        logger.info(
            "Admin linked TT username '%s' for user %s.",
            tt_username,
            user_settings.telegram_id,
        )

        is_relink = bool(original_tt_username and original_tt_username != tt_username)
        message_key = (
            "link_tt_account_success_relinked"
            if is_relink
            else "link_tt_account_success_linked"
        )
        return OperationResult(
            success=True,
            message_key=message_key,
            message_args={
                "new_tt_username": tt_username,
                "original_tt_username": original_tt_username or "",
            },
            user_settings=user_settings,
        )
