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
    ACTION_SUBSCRIBE_AND_LINK_NOON,
)

logger = logging.getLogger(__name__)

async def _handle_subscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    language: str,
    payload: Any,
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
    payload: Any,
    user_specific_settings: UserSpecificSettings # To update cache
) -> str:
    if await remove_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} unsubscribed via deeplink.")
        USER_SETTINGS_CACHE.pop(telegram_id, None) # Remove from cache on unsubscribe
        logger.info(f"Removed user {telegram_id} from settings cache after unsubscribe.")

        # Clear NOON settings upon unsubscription
        user_specific_settings.teamtalk_username = None
        user_specific_settings.not_on_online_confirmed = False
        user_specific_settings.not_on_online_enabled = False

        try:
            await update_user_settings_in_db(session, telegram_id, user_specific_settings)
            logger.info(f"Cleared NOON settings for user {telegram_id} due to unsubscription.")
        except Exception as e:
            # Log the error, but don't let it hide the unsubscription success from the user.
            # The main impact is that NOON settings might not be cleared in DB, but user is unsubscribed.
            logger.error(f"Failed to clear NOON settings in DB for user {telegram_id} during unsubscription: {e}", exc_info=True)

        return get_text("DEEPLINK_UNSUBSCRIBED", language)
    return get_text("DEEPLINK_NOT_SUBSCRIBED", language)


async def _handle_subscribe_and_link_noon_deeplink(
    session: AsyncSession,
    telegram_id: int,
    language: str,
    payload: str | None,
    user_specific_settings: UserSpecificSettings
) -> str:
    # Subscription Logic
    if await add_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} subscribed via combined deeplink.")
        # Ensure settings are loaded/created for the new subscriber, happens outside or implicitly by user_specific_settings presence
    else:
        logger.info(f"User {telegram_id} was already subscribed, proceeding to link NOON via combined deeplink.")

    current_settings = await get_or_create_user_settings(telegram_id, session)

    # Account Linking Logic
    tt_username_from_payload = payload
    if not tt_username_from_payload:
        logger.error(f"Deeplink for '{ACTION_SUBSCRIBE_AND_LINK_NOON}' missing payload for user {telegram_id}.")
        return get_text("DEEPLINK_NOON_CONFIRM_MISSING_PAYLOAD", language) # Re-use existing error for missing payload

    if current_settings.not_on_online_confirmed and \
       current_settings.teamtalk_username == tt_username_from_payload:
        # User is already confirmed with this same TeamTalk account.
        # Preserve existing 'not_on_online_enabled' status.
        # We still re-set username and confirmed status to ensure consistency,
        # though username is unlikely to change if it matches.
        current_settings.teamtalk_username = tt_username_from_payload
        current_settings.not_on_online_confirmed = True
        # NOT touching current_settings.not_on_online_enabled
        logger.info(f"User {telegram_id} re-confirmed NOON for TT user {tt_username_from_payload}. 'not_on_online_enabled' status preserved as {current_settings.not_on_online_enabled}.")
    else:
        # New NOON linking, or linking a different TeamTalk account.
        # Set 'not_on_online_enabled' to False by default.
        current_settings.teamtalk_username = tt_username_from_payload
        current_settings.not_on_online_confirmed = True
        current_settings.not_on_online_enabled = False # Explicitly set to False for new/changed linking
        logger.info(f"User {telegram_id} newly confirmed NOON for TT user {tt_username_from_payload}. 'not_on_online_enabled' set to False.")

    await update_user_settings_in_db(session, telegram_id, current_settings)

    final_tt_username = current_settings.teamtalk_username
    # Fallback for final_tt_username, though current_settings.teamtalk_username should be set by the logic above.
    if not final_tt_username: # Should ideally not be hit if previous logic is correct
        final_tt_username = tt_username_from_payload if tt_username_from_payload else "Unknown"

    # Always use DEEPLINK_SUBSCRIBED key
    message_key = "DEEPLINK_SUBSCRIBED"
    logger.info(f"User {telegram_id} subscribed and NOON linked for TT user {final_tt_username} via combined deeplink. Sending DEEPLINK_SUBSCRIBED message.")

    reply_text_val = get_text(message_key, language, tt_username=html.quote(final_tt_username))
    return reply_text_val


# Define a type for the handler functions
DeeplinkHandlerType = Callable[[AsyncSession, int, str, Any, UserSpecificSettings], Coroutine[Any, Any, str]]


DEEPLINK_ACTION_HANDLERS: dict[str, DeeplinkHandlerType] = {
    ACTION_SUBSCRIBE: _handle_subscribe_deeplink,
    ACTION_UNSUBSCRIBE: _handle_unsubscribe_deeplink,
    ACTION_SUBSCRIBE_AND_LINK_NOON: _handle_subscribe_and_link_noon_deeplink,
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
            if deeplink_obj.action == ACTION_SUBSCRIBE_AND_LINK_NOON:
                reply_text_val = await handler(session, telegram_id_val, language, deeplink_obj.payload, user_specific_settings)
            else:
                # For other actions like subscribe/unsubscribe, payload might not be directly used by handler logic
                reply_text_val = await handler(session, telegram_id_val, language, None, user_specific_settings)
        except Exception as e:
            logger.error(f"Error executing deeplink handler for action '{deeplink_obj.action}', token {token}: {e}", exc_info=True)
            reply_text_val = get_text("ERROR_OCCURRED", language)
    else:
        reply_text_val = get_text("DEEPLINK_INVALID_ACTION", language)
        logger.warning(f"Invalid deeplink action '{deeplink_obj.action}' for token {token}")

    await message.reply(reply_text_val)
    await delete_deeplink_by_token(session, token) # Delete after processing or attempt
