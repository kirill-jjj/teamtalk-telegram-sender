"""Service layer for handling deeplink actions."""

import gettext
import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import DeeplinkAction
from bot.core.user_settings import update_user_settings_in_db
from bot.database import crud
from bot.database.crud import add_subscriber
from bot.models import Deeplink as DeeplinkModel  # Renamed to avoid conflict
from bot.models import UserSettings
from bot.services import user_service

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
    if tt_username_from_payload and await crud.is_teamtalk_username_banned(session, tt_username_from_payload):
        logger.warning(
            "Subscription attempt with banned TeamTalk username: %s by Telegram ID: %s",
            tt_username_from_payload,
            telegram_id,
        )
        return _("The TeamTalk username '{tt_username}' is banned and cannot be linked.").format(
            tt_username=tt_username_from_payload
        )

    await add_subscriber(session, telegram_id)
    services.cache.add_subscriber(telegram_id) # Use CacheService
    logger.info("User %s added to subscribers list and cache via CacheService.", telegram_id)

    admin_record = await session.get(crud.Admin, telegram_id)
    if admin_record:
        services.cache.add_admin(telegram_id) # Use CacheService
        logger.info("User %s is an admin, added to admin_ids_cache via CacheService.", telegram_id)

    current_settings = user_settings
    if not tt_username_from_payload:  # Should be caught by DeeplinkModel validation if payload is non-optional
        logger.error(
            "Deeplink for '%s' missing TeamTalk username in payload for user %s.",
            DeeplinkAction.SUBSCRIBE,
            telegram_id,
        )
        return _("Error: Missing required information for subscription. Please try the link again or contact support.")

    current_settings.teamtalk_username = tt_username_from_payload
    current_settings.not_on_online_confirmed = True  # Assuming subscription implies confirmation
    await update_user_settings_in_db(session, current_settings)
    services.cache.update_user_settings(current_settings) # Use CacheService
    logger.info(
        "User %s linked to TT user '%s' and settings updated during subscription and in cache via CacheService.",
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
    else:
        logger.warning(
            "Attempted to unsubscribe user %s via deeplink, but user was not found or data deletion otherwise failed.",
            telegram_id,
        )
        return _("You were not subscribed to notifications.")


DEEPLINK_ACTION_HANDLERS = {
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

    # Ensure action_enum_member is a valid DeeplinkAction enum member
    if not isinstance(action_enum_member, DeeplinkAction):
        logger.warning("Action '%s' from token is not a valid DeeplinkAction member.", action_enum_member)
        return_message = _("Invalid deeplink action.")
    else:
        handler = DEEPLINK_ACTION_HANDLERS.get(action_enum_member)
        if not handler:
            logger.warning("No handler for deeplink action: %s", action_enum_member)
            return_message = _("Invalid deeplink action.")
        else:
            try:
                if action_enum_member == DeeplinkAction.UNSUBSCRIBE:
                    return_message = await handler(session, telegram_id, translator, services=services)
                elif action_enum_member == DeeplinkAction.SUBSCRIBE:
                    return_message = await handler(
                        session, telegram_id, translator, deeplink_obj.payload, user_settings, services=services
                    )
                else:
                    logger.error(
                        "Deeplink action %s not explicitly handled in execute_deeplink_action.", action_enum_member
                    )
                    return_message = _("Invalid deeplink action.")
            except (SQLAlchemyError, ValueError) as e_handler:
                logger.exception(
                    "Handler error for deeplink action '%s', token %s: %s",
                    action_enum_member,
                    deeplink_obj.token,  # Assuming DeeplinkModel has a token attribute
                    e_handler,
                )
                return_message = _("An error occurred. Please try again later.")
            except Exception as e_generic:
                logger.exception(
                    "Unexpected generic error for deeplink action '%s', token %s: %s",
                    action_enum_member,
                    deeplink_obj.token,
                    e_generic,
                )
                return_message = _("An error occurred. Please try again later.")
    return return_message
