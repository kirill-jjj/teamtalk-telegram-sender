"""Service layer for handling deeplink actions."""

from collections.abc import Awaitable, Callable
import gettext
import logging
from typing import TYPE_CHECKING, TypeGuard

from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import DeeplinkAction
from bot.database import crud
from bot.locales.keys import MSG_KEY_GENERIC_ERROR
from bot.models import Deeplink as DeeplinkModel  # Renamed to avoid conflict
from bot.models import UserSettings
from bot.services import user_service
from bot.services._utils import managed_db_transaction

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


async def process_subscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    translator: gettext.GNUTranslations,
    payload: str | None,
    user_settings: UserSettings,
    services: "Services",
) -> str:
    """Handles the logic for a subscribe deeplink."""
    _ = translator.gettext
    if await crud.is_telegram_id_banned(session, telegram_id):
        logger.warning("Subscription attempt by banned Telegram ID: %s", telegram_id)
        return _("Your Telegram account is banned from using this service.")

    tt_username_from_payload = payload
    if not tt_username_from_payload:  # Payload (TT username) is essential for subscription
        logger.error(
            "Deeplink for '%s' missing TeamTalk username in payload for user %s.",
            DeeplinkAction.SUBSCRIBE,
            telegram_id,
        )
        return _("Error: Missing required information for subscription. Please try the link again or contact support.")

    if await crud.is_teamtalk_username_banned(session, tt_username_from_payload):
        logger.warning(
            "Subscription attempt with banned TeamTalk username: %s by Telegram ID: %s",
            tt_username_from_payload,
            telegram_id,
        )
        return _("The TeamTalk username '{tt_username}' is banned and cannot be linked.").format(
            tt_username=tt_username_from_payload
        )

    # Call the new user_service function to handle subscription and core settings update
    subscription_processed = await user_service.process_new_subscription(
        session, user_settings, tt_username_from_payload, services
    )

    if not subscription_processed:
        logger.error(
            "Failed to process subscription for user %s with TT username '%s' via user_service.",
            telegram_id,
            tt_username_from_payload,
        )
        # The user_service.process_new_subscription should log specifics.
        # Provide a generic error to the user.
        return _("An error occurred during the subscription process. Please try again later or contact support.")

    # If user is also an admin, ensure admin cache is updated.
    # This check is done after successful subscription processing.
    admin_record = await session.get(crud.Admin, telegram_id)
    if admin_record:
        if not services.cache.is_admin(telegram_id):  # Check before adding to avoid redundant logs if already cached
            services.cache.add_admin(telegram_id)
            logger.info("User %s (subscriber) is also an admin, added to admin_ids_cache.", telegram_id)
        else:
            logger.info("User %s (subscriber) is also an admin, already in admin_ids_cache.", telegram_id)

    logger.info(
        "User %s successfully subscribed/settings updated with TT username '%s' via deeplink.",
        telegram_id,
        tt_username_from_payload,
    )
    return _("You have successfully subscribed to notifications.")


async def process_unsubscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    translator: gettext.GNUTranslations,
    services: "Services",
) -> str:
    """Handles the logic for an unsubscribe deeplink."""
    _ = translator.gettext
    if await user_service.delete_full_user_profile(session=session, telegram_id=telegram_id, services=services):
        logger.info("User %s unsubscribed and all data was deleted via deeplink (using user_service).", telegram_id)
        return _("You have successfully unsubscribed from notifications.")
    logger.warning(
        "Attempted to unsubscribe user %s via deeplink, but user was not found or data deletion otherwise failed.",
        telegram_id,
    )
    return _("You were not subscribed to notifications.")


# Define the expected signature for handler functions
# This is a simplified version; you might need to use a Protocol or more complex Callable
# if the signatures vary significantly and you want stricter checking for all.
SubscribeDeeplinkHandlerType = Callable[
    [AsyncSession, int, gettext.GNUTranslations, str | None, UserSettings, "Services"],
    Awaitable[str],
]
UnsubscribeDeeplinkHandlerType = Callable[[AsyncSession, int, gettext.GNUTranslations, "Services"], Awaitable[str]]

# Using a Union for the handler type to accommodate different signatures
DeeplinkHandler = SubscribeDeeplinkHandlerType | UnsubscribeDeeplinkHandlerType


def is_subscribe_handler(_handler: DeeplinkHandler, action: DeeplinkAction) -> TypeGuard[SubscribeDeeplinkHandlerType]:
    """Checks if the handler is for a subscribe action."""
    return action == DeeplinkAction.SUBSCRIBE


def is_unsubscribe_handler(
    _handler: DeeplinkHandler, action: DeeplinkAction
) -> TypeGuard[UnsubscribeDeeplinkHandlerType]:
    """Checks if the handler is for an unsubscribe action."""
    return action == DeeplinkAction.UNSUBSCRIBE


DEEPLINK_ACTION_HANDLERS: dict[DeeplinkAction, DeeplinkHandler] = {
    DeeplinkAction.SUBSCRIBE: process_subscribe_deeplink,
    DeeplinkAction.UNSUBSCRIBE: process_unsubscribe_deeplink,
}


async def execute_deeplink_action(
    deeplink_obj: DeeplinkModel,
    session: AsyncSession,
    telegram_id: int,
    translator: gettext.GNUTranslations,
    user_settings: UserSettings,  # Needed for subscribe
    services: "Services",
) -> str:
    """Selects and executes the correct deeplink processing function."""
    _ = translator.gettext  # For the "Invalid deeplink action" message
    action_enum_member = deeplink_obj.action
    return_message = ""

    if not isinstance(action_enum_member, DeeplinkAction):
        logger.warning("Action '%s' from token is not a valid DeeplinkAction member.", action_enum_member)
        return_message = _("Invalid deeplink action.")
    else:
        handler = DEEPLINK_ACTION_HANDLERS.get(action_enum_member)
        if not handler:
            logger.warning("No handler for deeplink action: %s", action_enum_member)
            return_message = _("Invalid deeplink action.")
        else:
            async with managed_db_transaction(session, logger) as transaction_success:
                if not transaction_success:
                    return _(MSG_KEY_GENERIC_ERROR)

                if is_unsubscribe_handler(handler, action_enum_member):
                    return_message = await handler(session, telegram_id, translator, services)
                elif is_subscribe_handler(handler, action_enum_member):
                    return_message = await handler(
                        session, telegram_id, translator, deeplink_obj.payload, user_settings, services
                    )
    return return_message
