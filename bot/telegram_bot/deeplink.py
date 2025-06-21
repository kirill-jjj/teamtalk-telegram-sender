# bot/telegram_bot/deeplink.py

import logging
from typing import Any, Callable, Coroutine, Optional

from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.enums import DeeplinkAction
from bot.models import UserSettings, Deeplink as DeeplinkModel, SubscribedUser # Added SubscribedUser
from bot.core.user_settings import (
    get_or_create_user_settings,
    update_user_settings_in_db,
)
from bot.database.crud import (
    add_subscriber,
    delete_deeplink_by_token,
    delete_user_data_fully,
)
from bot.database.crud import get_deeplink as db_get_deeplink

logger = logging.getLogger(__name__)


async def _validate_deeplink_token(
    session: AsyncSession, token: str, message_from_user_id: int, message: Message, _: callable
) -> Optional[DeeplinkModel]:
    """
    Validates the deeplink token and checks if it's intended for the current user.
    Sends a reply and returns None if validation fails.
    """
    deeplink_obj = await db_get_deeplink(session, token)
    if not deeplink_obj:
        await message.reply(_("Invalid or expired deeplink."))
        return None

    if deeplink_obj.expected_telegram_id and deeplink_obj.expected_telegram_id != message_from_user_id:
        await message.reply(_("This confirmation link was intended for a different Telegram account."))
        # Do not delete the deeplink here, as it might be for someone else.
        return None

    return deeplink_obj


async def _execute_deeplink_action(
    session: AsyncSession,
    telegram_id: int,
    _: callable,
    deeplink_obj: DeeplinkModel,
    user_settings: UserSettings,
    token: str
) -> str:
    """
    Executes the action specified by the deeplink object and returns a reply text.
    """
    action_enum_member = deeplink_obj.action

    if not isinstance(action_enum_member, DeeplinkAction):
        logger.warning(f"Action '{action_enum_member}' from token {token} is not a valid DeeplinkAction member.")
        return _("Invalid deeplink action.")

    handler_func = DEEPLINK_ACTION_HANDLERS.get(action_enum_member)
    if not handler_func:
        logger.warning(f"No handler found for DeeplinkAction member: {action_enum_member} from token {token}")
        return _("Invalid deeplink action.")

    try:
        if action_enum_member == DeeplinkAction.UNSUBSCRIBE:
            return await handler_func(session, telegram_id, _)
        else:
            # Pass user_settings to other handlers
            return await handler_func(session, telegram_id, _, deeplink_obj.payload, user_settings)

    except Exception as e:
        logger.error(f"Error executing deeplink handler for action '{action_enum_member}', token {token}: {e}", exc_info=True)
        return _("An error occurred.")


async def _handle_subscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable,
    payload: Any,
    user_settings: UserSettings
) -> str:
    if await add_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} subscribed via deeplink.")
        # Ensure settings are loaded/created and cached, get_or_create handles this.
        # The passed user_settings might be a new default one if this is the first interaction.
        # If it was already cached, it's passed here.
        # No specific update to user_settings needed here unless payload dictates it.
        await get_or_create_user_settings(telegram_id, session) # Ensures it's in cache if newly created by add_subscriber
        return _("You have successfully subscribed to notifications.")
    return _("You are already subscribed to notifications.")

async def _handle_unsubscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable
    # user_settings is not needed for unsubscribe action as per current logic
) -> str:
    if await delete_user_data_fully(session, telegram_id):
        logger.info(f"User {telegram_id} unsubscribed and all data was deleted via deeplink.")
        return _("You have successfully unsubscribed from notifications.")
    else:
        logger.warning(f"Attempted to unsubscribe user {telegram_id} via deeplink, but user was not found or data deletion otherwise failed.")
        return _("You were not subscribed to notifications.")


async def _handle_subscribe_and_link_noon_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable,
    payload: str | None,
    user_settings: UserSettings
) -> str:
    if not await session.get(UserSettings, telegram_id):
        await add_subscriber(session, telegram_id)
        logger.info(f"User {telegram_id} added to subscribers list via NOON deeplink.")
        current_settings = await get_or_create_user_settings(telegram_id, session)
    else:
        if not await session.get(SubscribedUser, telegram_id): # Use direct import
             await add_subscriber(session, telegram_id)
             logger.info(f"User {telegram_id} (with existing settings) added to subscribers list via NOON deeplink.")
        current_settings = user_settings

    tt_username_from_payload = payload
    if not tt_username_from_payload:
        logger.error(f"Deeplink for '{DeeplinkAction.SUBSCRIBE_AND_LINK_NOON}' missing payload for user {telegram_id}.")
        return _("Error: Missing TeamTalk username in confirmation link.")

    current_settings.teamtalk_username = tt_username_from_payload
    current_settings.not_on_online_confirmed = True
    await update_user_settings_in_db(session, current_settings)
    logger.info(f"User {telegram_id} linked NOON to TT user {tt_username_from_payload} and settings updated.")

    return _("You have successfully subscribed to notifications.")


DeeplinkHandlerType = Callable[
    [AsyncSession, int, callable, Any, UserSettings],
    Coroutine[Any, Any, str]
]

UnsubscribeDeeplinkHandlerType = Callable[
    [AsyncSession, int, callable],
    Coroutine[Any, Any, str]
]

DEEPLINK_ACTION_HANDLERS: dict[DeeplinkAction, Any] = {
    DeeplinkAction.SUBSCRIBE: _handle_subscribe_deeplink,
    DeeplinkAction.UNSUBSCRIBE: _handle_unsubscribe_deeplink,
    DeeplinkAction.SUBSCRIBE_AND_LINK_NOON: _handle_subscribe_and_link_noon_deeplink,
}


async def handle_deeplink_payload(
    message: Message,
    token: str,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings
):
    if not message.from_user:
        logger.warning("Cannot handle deeplink: message.from_user is None.")
        await message.reply(_("An error occurred."))
        return

    message_from_user_id = message.from_user.id

    # _validate_deeplink_token expects bot.models.Deeplink from db_get_deeplink
    deeplink_obj: Optional[DeeplinkModel] = await _validate_deeplink_token(session, token, message_from_user_id, message, _)
    if not deeplink_obj:
        return

    # user_settings is already fetched by the middleware and passed in.
    # For SUBSCRIBE_AND_LINK_NOON, this user_settings object will be updated.
    # For SUBSCRIBE, it's used to ensure consistency if needed.
    reply_text = await _execute_deeplink_action(
        session,
        message_from_user_id,
        _,
        deeplink_obj, # This is DeeplinkModel instance
        user_settings, # This is UserSettings SQLModel instance
        token
    )

    await message.reply(reply_text)
    # db_delete_deeplink_by_token expects the token string
    await delete_deeplink_by_token(session, token)
