"""Service for managing user subscriptions."""

from gettext import NullTranslations
import logging
from typing import Annotated

from pydantic import ConfigDict, Field, validate_call

from bot.database.uow import IUnitOfWork
from bot.models import SubscribedUser, UserSettings
from bot.services.cache_service import CacheService
from bot.services.schemas import OperationResult

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

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def create_subscription(
        self,
        user_settings: UserSettings,
        tt_username: str,
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

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def delete_profile(
        self,
        telegram_id: Annotated[int, Field(gt=0)],
        translator: NullTranslations,
    ) -> OperationResult:
        """Orchestrates the full deletion of a user's profile from DB and cache."""
        _ = translator.gettext
        logger.info("Deleting full user profile for Telegram ID: %s", telegram_id)

        async with self._uow:
            user_settings = await self._uow.users.get_by_id(telegram_id)
            if user_settings:
                await self._uow.users.delete(user_settings)

            subscriber = await self._uow.subscribers.get_by_id(telegram_id)
            if subscriber:
                await self._uow.subscribers.delete(subscriber)

            await self._uow.commit()

        self._cache.remove_user_profile(telegram_id)
        logger.info(
            "Full user profile deletion process completed for Telegram ID: %s.",
            telegram_id,
        )
        return OperationResult(
            success=True,
            message_key=_("Subscriber {telegram_id} deleted successfully."),
            message_args={"telegram_id": telegram_id},
        )

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def link_tt_account(
        self,
        user_settings: UserSettings,
        tt_username: str,
        translator: NullTranslations,
    ) -> OperationResult:
        """Links a TeamTalk account to a subscriber."""
        _ = translator.gettext

        async with self._uow:
            if await self._uow.bans.is_teamtalk_username_banned(tt_username):
                logger.warning(
                    "Attempt to link banned TT username '%s' to user %s.",
                    tt_username,
                    user_settings.telegram_id,
                )
                return OperationResult(
                    success=False,
                    message_key=_(
                        "Cannot link TeamTalk account: "
                        "username {tt_username} is banned."
                    ),
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
            _(
                "Successfully relinked TeamTalk account to {new_tt_username} "
                "(was {original_tt_username})."
            )
            if is_relink
            else _("Successfully linked TeamTalk account: {new_tt_username}.")
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
