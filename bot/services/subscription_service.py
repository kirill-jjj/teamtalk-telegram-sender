"""Service for managing user subscriptions."""

from gettext import NullTranslations
import logging
from typing import Annotated

from pydantic import ConfigDict, Field, validate_call

from bot.database.models import SubscribedUser
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.schemas import OperationResult
from bot.services.teamtalk_service import TeamTalkService

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Service for managing user subscriptions."""

    def __init__(
        self, uow: IUnitOfWork, cache: CacheService, teamtalk_service: TeamTalkService
    ) -> None:
        """Initializes the subscription service.

        Args:
            uow: The unit of work.
            cache: The cache service.
            teamtalk_service: The TeamTalk service.
        """
        self._uow = uow
        self._cache = cache
        self._teamtalk_service = teamtalk_service

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def create_subscription(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        default_lang: str,
        tt_username: str,
    ) -> OperationResult:
        """Creates a new subscription, updating the database and cache."""
        user_settings = await uow.users.get_or_create(
            telegram_id, defaults={"language_code": default_lang}
        )
        message_key = "subscription_updated"

        subscriber = await uow.subscribers.get_by_id(telegram_id)
        if not subscriber:
            new_subscriber = SubscribedUser(telegram_id=telegram_id)
            await uow.subscribers.add(new_subscriber)
            logger.info("User %s newly subscribed.", telegram_id)
            self._cache.add_subscriber(telegram_id)
            message_key = "subscription_created"
        else:
            logger.info("User %s re-confirmed subscription.", telegram_id)

        user_settings.teamtalk_username = tt_username
        user_settings.not_on_online_confirmed = True
        await uow.users.save(user_settings)

        logger.debug(
            "Linked TT username '%s' and confirmed NOON for user %s.",
            tt_username,
            telegram_id,
        )
        self._cache.update_user_settings(user_settings)
        return OperationResult(success=True, message_key=message_key)

    @validate_call(config=ConfigDict(arbitrary_types_allowed=True))
    async def delete_profile(
        self,
        uow: IUnitOfWork,
        telegram_id: Annotated[int, Field(gt=0)],
        translator: NullTranslations,
    ) -> OperationResult:
        """Deletes a user's profile from the database and cache."""
        _ = translator.gettext
        logger.info("Deleting full user profile for Telegram ID: %s", telegram_id)

        user_settings = await uow.users.get_by_id(telegram_id)
        if user_settings:
            await uow.users.delete(user_settings)

        subscriber = await uow.subscribers.get_by_id(telegram_id)
        if subscriber:
            await uow.subscribers.delete(subscriber)

        # Commit is handled by the calling UoW context

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
        uow: IUnitOfWork,
        telegram_id: int,
        tt_username: str,
        default_lang: str,
        translator: NullTranslations,
    ) -> OperationResult:
        """Links a TeamTalk account to a subscriber."""
        _ = translator.gettext
        user_settings = await uow.users.get_or_create(
            telegram_id, defaults={"language_code": default_lang}
        )

        if await uow.bans.is_teamtalk_username_banned(tt_username):
            logger.warning(
                "Attempt to link banned TT username '%s' to user %s.",
                tt_username,
                user_settings.telegram_id,
            )
            return OperationResult(
                success=False,
                message_key=_(
                    "Cannot link TeamTalk account: username {tt_username} is banned."
                ),
                message_args={"tt_username": tt_username},
            )

        original_tt_username = user_settings.teamtalk_username
        user_settings.teamtalk_username = tt_username
        user_settings.not_on_online_confirmed = True
        await uow.users.save(user_settings)

        self._cache.update_user_settings(user_settings)
        logger.debug(
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
