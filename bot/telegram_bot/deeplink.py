import logging
from typing import Callable, Coroutine, Any
from aiogram import html
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import (
    add_subscriber,
    remove_subscriber,
    get_deeplink as db_get_deeplink,
    delete_deeplink_by_token
)
from bot.database.models import UserSettings # For type hint
from bot.core.user_settings import (
    USER_SETTINGS_CACHE,
    UserSpecificSettings,
    get_or_create_user_settings,
    update_user_settings_in_db
)
from bot.localization import get_text
from bot.constants import (
    ACTION_SUBSCRIBE,
    ACTION_UNSUBSCRIBE,
    ACTION_CONFIRM_NOON,
)

logger = logging.getLogger(__name__)

async def _handle_subscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    language: str,
    user_specific_settings: UserSpecificSettings # To update cache if needed
) -> str:
    if await add_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} subscribed via deeplink.")
        # Ensure settings are loaded/created for the new subscriber
        await get_or_create_user_settings(telegram_id, session)
        return get_text("DEEPLINK_SUBSCRIBED", language)
    return get_text("DEEPLINK_ALREADY_SUBSCRIBED", language)

async def _handle_unsubscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    language: str,
    user_specific_settings: UserSpecificSettings # To update cache
) -> str:
    if await remove_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} unsubscribed via deeplink.")
        USER_SETTINGS_CACHE.pop(telegram_id, None) # Remove from cache on unsubscribe
        # Optionally, delete UserSettings row from DB or mark as inactive
        # For now, we just remove from cache; settings row remains for potential re-subscribe.
        logger.info(f"Removed user {telegram_id} from settings cache after unsubscribe.")
        return get_text("DEEPLINK_UNSUBSCRIBED", language)
    return get_text("DEEPLINK_NOT_SUBSCRIBED", language)

async def _handle_confirm_noon_deeplink(
    session: AsyncSession,
    telegram_id: int,
    language: str,
    payload: str | None,
    user_specific_settings: UserSpecificSettings # To update
) -> str:
    tt_username_from_payload = payload
    if not tt_username_from_payload:
        logger.error("Deeplink for 'confirm_not_on_online' missing payload.")
        return get_text("DEEPLINK_NOON_CONFIRM_MISSING_PAYLOAD", language)

    # Update UserSpecificSettings object directly
    user_specific_settings.teamtalk_username = tt_username_from_payload
    user_specific_settings.not_on_online_enabled = True # Enable by default on confirmation
    user_specific_settings.not_on_online_confirmed = True

    # Persist changes to DB and update cache
    await update_user_settings_in_db(session, telegram_id, user_specific_settings)

    logger.info(f"User {telegram_id} confirmed 'not on online' for TT user {tt_username_from_payload} via deeplink.")
    return get_text("DEEPLINK_NOON_CONFIRMED", language, tt_username=html.quote(tt_username_from_payload))


# Define a type for the handler functions
DeeplinkHandlerType = Callable[[AsyncSession, int, str, Any, UserSpecificSettings], Coroutine[Any, Any, str]]


DEEPLINK_ACTION_HANDLERS: dict[str, DeeplinkHandlerType] = {
    ACTION_SUBSCRIBE: _handle_subscribe_deeplink,
    ACTION_UNSUBSCRIBE: _handle_unsubscribe_deeplink,
    ACTION_CONFIRM_NOON: _handle_confirm_noon_deeplink,
}


async def handle_deeplink_payload(
    message: Message,
    token: str,
    session: AsyncSession,
    language: str, # This is the user's current language setting
    user_specific_settings: UserSpecificSettings # User's current settings object
):
    if not message.from_user:
        logger.warning("Cannot handle deeplink: message.from_user is None.")
        await message.reply(get_text("ERROR_OCCURRED", language)) # Generic error
        return

    deeplink_obj = await db_get_deeplink(session, token)
    if not deeplink_obj:
        await message.reply(get_text("DEEPLINK_INVALID_OR_EXPIRED", language))
        return

    telegram_id_val = message.from_user.id
    reply_text_val = get_text("ERROR_OCCURRED", language) # Default error message

    if deeplink_obj.expected_telegram_id and deeplink_obj.expected_telegram_id != telegram_id_val:
        await message.reply(get_text("DEEPLINK_WRONG_ACCOUNT", language))
        # Do not delete the deeplink here, it might be for someone else who hasn't clicked yet.
        # Or, if one-time use per link is strict, delete it. For now, let it expire.
        return

    handler = DEEPLINK_ACTION_HANDLERS.get(deeplink_obj.action)
    if handler:
        try:
            # Pass necessary arguments to the handler
            # For confirm_noon, payload is tt_username. For others, it might be None or different.
            if deeplink_obj.action == ACTION_CONFIRM_NOON:
                reply_text_val = await handler(session, telegram_id_val, language, deeplink_obj.payload, user_specific_settings)
            else:
                # For subscribe/unsubscribe, payload is not directly used by handler logic but could be passed if needed
                reply_text_val = await handler(session, telegram_id_val, language, None, user_specific_settings)
        except Exception as e:
            logger.error(f"Error executing deeplink handler for action '{deeplink_obj.action}', token {token}: {e}", exc_info=True)
            reply_text_val = get_text("ERROR_OCCURRED", language)
    else:
        reply_text_val = get_text("DEEPLINK_INVALID_ACTION", language)
        logger.warning(f"Invalid deeplink action '{deeplink_obj.action}' for token {token}")

    await message.reply(reply_text_val)
    await delete_deeplink_by_token(session, token) # Delete after processing or attempt
