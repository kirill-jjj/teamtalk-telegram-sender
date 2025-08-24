"""Service layer for handling deeplink actions."""

from gettext import NullTranslations
import logging

from aiogram.types import Message

from bot.constants import MSG_GENERAL_ERROR
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

    async def create_tt_deeplink_reply(
        self,
        translator: NullTranslations,
        action: DeeplinkAction,
        ttl_seconds: int,
        payload: str | None = None,
    ) -> str:
        """Creates a deeplink and returns the full localized reply text for TeamTalk."""
        _ = translator.gettext
        async with self._uow:
            deeplink = await self._uow.deeplinks.create(
                action,
                ttl_seconds,
                payload=payload,
            )
            await self._uow.commit()

        bot_username = self._cache.get_bot_username()
        if not bot_username:
            logger.error("Bot username not found in cache. Cannot create deeplink.")
            return _("Could not generate a link, bot username is not configured.")

        deeplink_url = f"https://t.me/{bot_username}?start={deeplink.token}"
        logger.info(
            "Generated deeplink %s for TT user %s",
            deeplink.token,
            payload or "(no payload)",
        )

        reply_text_map = {
            DeeplinkAction.SUBSCRIBE: _(
                "Click this link to subscribe to notifications "
                "(link valid for 5 minutes):\n{deeplink_url}"
            ),
            DeeplinkAction.UNSUBSCRIBE: _(
                "Click this link to unsubscribe from notifications "
                "(link valid for 5 minutes):\n{deeplink_url}"
            ),
        }
        reply_text_source = reply_text_map.get(
            action, "Invalid action for deeplink."
        )

        return reply_text_source.format(deeplink_url=deeplink_url)

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
            return _(MSG_GENERAL_ERROR)

        if await uow.admins.get_by_id(telegram_id):
            self._cache.add_admin(telegram_id)

        return _("You have successfully subscribed to notifications.")

    async def _execute_unsubscribe(
        self, telegram_id: int, translator: NullTranslations, uow: IUnitOfWork
    ) -> str:
        """Handles the logic for an unsubscribe deeplink."""
        _ = translator.gettext
        if await self._subscription_service.delete_profile(
            telegram_id, translator, uow=uow
        ):
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

    async def process_telegram_deeplink(
        self,
        message: Message,
        token: str,
        translator: NullTranslations,
        user_settings: UserSettings,
    ) -> None:
        """Handles a /start command with a deeplink token.

        Validates the token, executes the associated action, and replies to the user.

        Args:
            message: The Aiogram Message object.
            token: The deeplink token from the command arguments.
            translator: The gettext translator object.
            user_settings: The UserSettings object for the user.
        """
        _ = translator.gettext
        if not message.from_user:
            logger.warning("Cannot handle deeplink: message.from_user is None.")
            await message.reply(_(MSG_GENERAL_ERROR))
            return

        deeplink = await self._uow.deeplinks.get_and_delete_if_expired(token)
        if not deeplink:
            await message.reply(_("Invalid or expired deeplink."))
            return

        if (
            deeplink.expected_telegram_id
            and deeplink.expected_telegram_id != message.from_user.id
        ):
            await message.reply(
                _(
                    "This confirmation link was intended for a different "
                    "Telegram account."
                )
            )
            return

        reply_text = await self.execute_deeplink(
            deeplink, user_settings, translator, self._uow
        )
        await message.reply(reply_text)

        # The token is now used, so we should delete it.
        await self._uow.deeplinks.delete(deeplink)
