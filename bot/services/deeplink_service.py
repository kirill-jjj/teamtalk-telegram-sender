"""Service layer for handling deeplink actions."""

from gettext import NullTranslations
import logging

from bot.core.enums import DeeplinkAction
from bot.database.models import Deeplink as DeeplinkModel
from bot.database.models import UserSettings
from bot.database.uow import IUnitOfWork
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

    @staticmethod
    async def create_deeplink(
        uow: IUnitOfWork,
        action: DeeplinkAction,
        ttl_seconds: int,
        payload: str | None = None,
    ) -> DeeplinkModel:
        """Creates and saves a deeplink, returning the model."""
        deeplink = await uow.deeplinks.create(
            action,
            ttl_seconds,
            payload=payload,
        )
        logger.info(
            "Generated deeplink %s for TT user %s",
            deeplink.token,
            payload or "(no payload)",
        )
        return deeplink

    async def _execute_subscribe(
        self,
        uow: IUnitOfWork,
        telegram_id: int,
        translator: NullTranslations,
        payload: str | None,
        user_settings: UserSettings,
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
            uow, user_settings, payload
        )
        if not success:
            return _("An error occurred. Please try again later.")

        # Cache update for user_settings is now handled here
        # after successful subscription
        self._cache.update_user_settings(user_settings)

        # Check if the user is an admin and add them to the cache
        if await uow.admins.get_by_id(telegram_id):
            self._cache.add_admin(telegram_id)

        return _("You have successfully subscribed to notifications.")

    async def _execute_unsubscribe(
        self, uow: IUnitOfWork, telegram_id: int, translator: NullTranslations
    ) -> str:
        """Handles the logic for an unsubscribe deeplink."""
        _ = translator.gettext
        if await self._subscription_service.delete_profile(
            uow, telegram_id, translator
        ):
            return _("You have successfully unsubscribed from notifications.")
        return _("You were not subscribed to notifications.")

    async def execute_deeplink(
        self,
        uow: IUnitOfWork,
        deeplink: DeeplinkModel,
        user_settings: UserSettings,
        translator: NullTranslations,
    ) -> str:
        """Selects and executes the correct deeplink processing function."""
        telegram_id = user_settings.telegram_id
        action = deeplink.action

        if action == DeeplinkAction.SUBSCRIBE:
            return await self._execute_subscribe(
                uow, telegram_id, translator, deeplink.payload, user_settings
            )
        if action == DeeplinkAction.UNSUBSCRIBE:
            return await self._execute_unsubscribe(uow, telegram_id, translator)

        logger.warning("No handler for deeplink action: %s", action)
        return translator.gettext("Invalid deeplink action.")

    async def execute_telegram_deeplink(
        self,
        uow: IUnitOfWork,
        token: str,
        translator: NullTranslations,
        telegram_id: int,
        default_lang: str,
    ) -> tuple[str, bool]:
        """Handles a /start command with a deeplink token.

        Validates the token, executes the associated action, and replies to the user.

        Args:
            uow: The unit of work.
            token: The deeplink token from the command arguments.
            translator: The gettext translator object.
            telegram_id: The telegram id of the user.
            default_lang: The default language code from settings.
        """
        _ = translator.gettext

        user_settings = await uow.users.get_or_create(
            telegram_id, defaults={"language_code": default_lang}
        )

        deeplink = await uow.deeplinks.resolve_token(token)
        if not deeplink:
            return _("Invalid or expired deeplink."), False

        if (
            deeplink.expected_telegram_id
            and deeplink.expected_telegram_id != telegram_id
        ):
            return (
                _(
                    "This confirmation link was intended for a different "
                    "Telegram account."
                ),
                False,
            )

        reply_text = await self.execute_deeplink(
            uow, deeplink, user_settings, translator
        )

        # The token is now used, so we should delete it.
        await uow.deeplinks.delete(deeplink)
        return reply_text, True
