"""Service layer for handling deeplink actions."""

from gettext import NullTranslations
import logging

from bot.core.enums import DeeplinkAction
from bot.database.uow import IUnitOfWork
from bot.models import Deeplink as DeeplinkModel
from bot.models import UserSettings
from bot.services.cache_service import CacheService
from bot.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class DeeplinkService:
    """Service for executing actions associated with deeplinks."""

    def __init__(
        self,
        uow: IUnitOfWork,
        subscription_service: SubscriptionService,
        cache: CacheService,
    ) -> None:
        """Initializes the deeplink service."""
        self._uow = uow
        self._subscription_service = subscription_service
        self._cache = cache

    async def _execute_subscribe(
        self,
        telegram_id: int,
        translator: NullTranslations,
        payload: str | None,
        user_settings: UserSettings,
        uow: IUnitOfWork,
    ) -> str:
        """Handles the logic for a subscribe deeplink."""
        _ = translator.gettext
        if await uow.bans.is_telegram_id_banned(telegram_id):
            logger.warning(
                "Subscription attempt by banned Telegram ID: %s", telegram_id
            )
            return _("Your Telegram account is banned from using this service.")

        if not payload:
            logger.error("Subscribe deeplink missing payload for user %s.", telegram_id)
            return _("Error: Missing required information for subscription.")

        if await uow.bans.is_teamtalk_username_banned(payload):
            logger.warning(
                "Subscription attempt with banned TT username: %s by TG ID: %s",
                payload,
                telegram_id,
            )
            return _("The TeamTalk username '{tt_username}' is banned.").format(
                tt_username=payload
            )

        success = await self._subscription_service.create_subscription(
            user_settings, payload, uow=uow
        )
        if not success:
            return _("An error occurred. Please try again later.")

        if await uow.admins.get_by_id(telegram_id):
            self._cache.add_admin(telegram_id)

        return _("You have successfully subscribed to notifications.")

    async def _execute_unsubscribe(
        self, telegram_id: int, translator: NullTranslations, uow: IUnitOfWork
    ) -> str:
        """Handles the logic for an unsubscribe deeplink."""
        _ = translator.gettext
        if await self._subscription_service.delete_profile(telegram_id, uow=uow):
            return _("You have successfully unsubscribed from notifications.")
        return _("You were not subscribed to notifications.")

    async def execute_deeplink(
        self,
        deeplink: DeeplinkModel,
        user_settings: UserSettings,
        translator: NullTranslations,
        uow: IUnitOfWork,
    ) -> str:
        """Selects and executes the correct deeplink processing function."""
        telegram_id = user_settings.telegram_id
        action = deeplink.action

        if action == DeeplinkAction.SUBSCRIBE:
            return await self._execute_subscribe(
                telegram_id, translator, deeplink.payload, user_settings, uow
            )
        if action == DeeplinkAction.UNSUBSCRIBE:
            return await self._execute_unsubscribe(telegram_id, translator, uow)

        logger.warning("No handler for deeplink action: %s", action)
        return translator.gettext("Invalid deeplink action.")
