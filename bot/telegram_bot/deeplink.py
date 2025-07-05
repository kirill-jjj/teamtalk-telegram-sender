
import logging
from typing import Any, Callable, Coroutine, Optional, TYPE_CHECKING

from aiogram.types import Message
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.enums import DeeplinkAction
from bot.models import UserSettings, Deeplink as DeeplinkModel
from bot.core.user_settings import (
    update_user_settings_in_db,
)
from bot.database.crud import (
    add_subscriber,
    delete_deeplink_by_token,
)
from bot.database import crud
from bot.database.crud import get_deeplink as db_get_deeplink
from bot.services import user_service # Import the new service

# Add import Application for Type Hinting
if TYPE_CHECKING:
    from sender import Application

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
    token: str,
    app: "Application"
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
            return await handler_func(session, telegram_id, _, app=app)
        else:
            return await handler_func(session, telegram_id, _, deeplink_obj.payload, user_settings, app=app)

    except (SQLAlchemyError, ValueError) as e_handler:
        logger.error(f"Handler error for deeplink action '{action_enum_member}', token {token}: {e_handler}", exc_info=True)
        return _("An error occurred. Please try again later.")


async def _handle_unsubscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable,
    app: "Application"
) -> str:
    if await user_service.delete_full_user_profile(session=session, telegram_id=telegram_id, app=app):
        logger.info(f"User {telegram_id} unsubscribed and all data was deleted via deeplink (using user_service).")
        return _("You have successfully unsubscribed from notifications.")
    else:
        logger.warning(f"Attempted to unsubscribe user {telegram_id} via deeplink, but user was not found or data deletion otherwise failed.")
        return _("You were not subscribed to notifications.")


async def _handle_subscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable,
    payload: str | None, # Expecting TeamTalk username as payload
    user_settings: UserSettings,
    app: "Application"
) -> str:
    # --- Ban Check ---
    if await crud.is_telegram_id_banned(session, telegram_id):
        logger.warning(f"Subscription attempt by banned Telegram ID: {telegram_id}")
        return _("Your Telegram account is banned from using this service.")

    tt_username_from_payload = payload
    if tt_username_from_payload and await crud.is_teamtalk_username_banned(session, tt_username_from_payload):
        logger.warning(f"Subscription attempt with banned TeamTalk username: {tt_username_from_payload} by Telegram ID: {telegram_id}")
        return _("The TeamTalk username '{tt_username}' is banned and cannot be linked.").format(tt_username=tt_username_from_payload)
    # --- End Ban Check ---

    await add_subscriber(session, telegram_id)
    # Update cache directly using app instance
    app.subscribed_users_cache.add(telegram_id)
    logger.info(f"User {telegram_id} added to subscribers list and cache.")

    # If the user is an admin in the DB, add them to the admin_ids_cache as well
    # This handles the case where an admin unsubscribes and then re-subscribes via deeplink
    admin_record = await session.get(crud.Admin, telegram_id) # Use crud.Admin to access the model
    if admin_record:
        app.admin_ids_cache.add(telegram_id)
        logger.info(f"User {telegram_id} is an admin, added to admin_ids_cache.")

    # The user_settings passed in is from middleware, it's already get_or_created.
    current_settings = user_settings

    tt_username_from_payload = payload
    if not tt_username_from_payload:
        # Since this is the standard subscription, payload is now expected.
        logger.error(f"Deeplink for '{DeeplinkAction.SUBSCRIBE}' missing TeamTalk username in payload for user {telegram_id}.")
        return _("Error: Missing required information for subscription. Please try the link again or contact support.")

    current_settings.teamtalk_username = tt_username_from_payload
    current_settings.not_on_online_confirmed = True
    await update_user_settings_in_db(session, current_settings)
    # Update cache directly using app instance
    app.user_settings_cache[telegram_id] = current_settings
    logger.info(f"User {telegram_id} linked to TT user '{tt_username_from_payload}' and settings updated during subscription and in cache.")

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
}


async def handle_deeplink_payload(
    message: Message,
    token: str,
    session: AsyncSession,
    _: callable,
    user_settings: UserSettings,
    app: "Application"
):
    if not message.from_user:
        logger.warning("Cannot handle deeplink: message.from_user is None.")
        await message.reply(_("An error occurred. Please try again later."))
        return

    message_from_user_id = message.from_user.id

    # _validate_deeplink_token expects bot.models.Deeplink from db_get_deeplink
    deeplink_obj: Optional[DeeplinkModel] = await _validate_deeplink_token(session, token, message_from_user_id, message, _)
    if not deeplink_obj:
        return

    # user_settings is already fetched by middleware. It's used/updated by the action handler.
    reply_text = await _execute_deeplink_action(
        session,
        message_from_user_id,
        _,
        deeplink_obj,
        user_settings,
        token,
        app=app
    )

    await message.reply(reply_text)
    # db_delete_deeplink_by_token expects the token string
    await delete_deeplink_by_token(session, token)
