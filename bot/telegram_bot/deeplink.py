import logging
from typing import Any, Callable, Coroutine, Optional

from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.enums import DeeplinkAction
from bot.core.user_settings import (
    UserSpecificSettings,
    get_or_create_user_settings,
    update_user_settings_in_db,
)
from bot.database.crud import (
    add_subscriber,
    delete_deeplink_by_token,
    delete_user_data_fully,
)
from bot.database.crud import get_deeplink as db_get_deeplink
from bot.database.models import Deeplink

logger = logging.getLogger(__name__)


async def _validate_deeplink_token(
    session: AsyncSession, token: str, message_from_user_id: int, message: Message, _: callable
) -> Optional[Deeplink]:
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
    deeplink_obj: Deeplink,
    user_specific_settings: UserSpecificSettings,
    token: str
) -> str:
    """
    Executes the action specified by the deeplink object and returns a reply text.
    """
    # SQLAlchemy уже преобразовал значение из БД в нужный нам enum.
    # Просто используем его, убедившись, что это действительно член нашего enum.
    action_enum_member = deeplink_obj.action

    if not isinstance(action_enum_member, DeeplinkAction):
        logger.warning(f"Action '{action_enum_member}' from token {token} is not a valid DeeplinkAction member.")
        return _("Invalid deeplink action.")

    handler_func = DEEPLINK_ACTION_HANDLERS.get(action_enum_member)
    if not handler_func:
        logger.warning(f"No handler found for DeeplinkAction member: {action_enum_member} from token {token}")
        return _("Invalid deeplink action.")

    try:
        # Учитываем, что у разных обработчиков разные сигнатуры.
        if action_enum_member == DeeplinkAction.UNSUBSCRIBE:
            # Обработчик для отписки не требует payload и user_specific_settings
            return await handler_func(session, telegram_id, _)
        else:
            # Обработчики для подписки и связывания аккаунта требуют больше аргументов
            return await handler_func(session, telegram_id, _, deeplink_obj.payload, user_specific_settings)

    except Exception as e:
        logger.error(f"Error executing deeplink handler for action '{action_enum_member}', token {token}: {e}", exc_info=True)
        return _("An error occurred.")


async def _handle_subscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable,
    payload: Any,
    user_specific_settings: UserSpecificSettings
) -> str:
    if await add_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} subscribed via deeplink.")
        await get_or_create_user_settings(telegram_id, session)
        return _("You have successfully subscribed to notifications.")
    return _("You are already subscribed to notifications.")

async def _handle_unsubscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable
) -> str:
    if await delete_user_data_fully(session, telegram_id): # delete_user_data_fully now also clears USER_SETTINGS_CACHE
        logger.info(f"User {telegram_id} unsubscribed and all data was deleted via deeplink.")
        return _("You have successfully unsubscribed from notifications.")
    else:
        # This case implies user was not found initially by delete_user_data_fully or deletion failed.
        logger.warning(f"Attempted to unsubscribe user {telegram_id} via deeplink, but user was not found or data deletion otherwise failed.")
        return _("You were not subscribed to notifications.")


async def _handle_subscribe_and_link_noon_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable,
    payload: str | None,
    user_specific_settings: UserSpecificSettings
) -> str:
    if await add_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} successfully subscribed via deeplink.")
    else:
        logger.info(f"User {telegram_id} was already in the subscribers list.")

    current_settings = await get_or_create_user_settings(telegram_id, session)

    tt_username_from_payload = payload
    if not tt_username_from_payload:
        logger.error(f"Deeplink for '{DeeplinkAction.SUBSCRIBE_AND_LINK_NOON}' missing payload for user {telegram_id}.")
        return _("Error: Missing TeamTalk username in confirmation link.")

    current_settings.teamtalk_username = tt_username_from_payload
    current_settings.not_on_online_confirmed = True
    logger.info(f"User {telegram_id} linked NOON to TT user {tt_username_from_payload}.")

    await update_user_settings_in_db(session, telegram_id, current_settings)

    return _("You have successfully subscribed to notifications.")


# Adjusted for _handle_unsubscribe_deeplink taking fewer params
# For others, payload is Any (was str | None for NOON link, Any for subscribe)
# UserSpecificSettings is not always used by all handlers after refactor, but kept for type consistency if possible
DeeplinkHandlerType = Callable[
    [AsyncSession, int, callable, Any, UserSpecificSettings],
    Coroutine[Any, Any, str]
]
# A more specific type for unsubscribe might be needed if strict typing is paramount
UnsubscribeDeeplinkHandlerType = Callable[
    [AsyncSession, int, callable],
    Coroutine[Any, Any, str]
]

DEEPLINK_ACTION_HANDLERS: dict[DeeplinkAction, Any] = {
    DeeplinkAction.SUBSCRIBE: _handle_subscribe_deeplink,
    DeeplinkAction.UNSUBSCRIBE: _handle_unsubscribe_deeplink, # type: ignore
    DeeplinkAction.SUBSCRIBE_AND_LINK_NOON: _handle_subscribe_and_link_noon_deeplink,
}


async def handle_deeplink_payload(
    message: Message,
    token: str,
    session: AsyncSession,
    _: callable,
    user_specific_settings: UserSpecificSettings
):
    if not message.from_user:
        logger.warning("Cannot handle deeplink: message.from_user is None.")
        # Attempt to reply to the message if possible, though message.from_user is None.
        # This situation is tricky; replying without a target user context might not be ideal
        # or even possible depending on the Telegram Bot API behavior for `message.reply`
        # when `message.from_user` is not available.
        # For now, we'll keep the original behavior of trying to reply.
        await message.reply(_("An error occurred."))
        return

    message_from_user_id = message.from_user.id

    deeplink_obj = await _validate_deeplink_token(session, token, message_from_user_id, message, _)
    if not deeplink_obj:
        # _validate_deeplink_token sends reply and returns None.
        # The main function then returns. This means the token is NOT deleted if validation fails.
        # This is probably better than deleting a token meant for another user.
        return


    reply_text = await _execute_deeplink_action(
        session,
        message_from_user_id,
        _,
        deeplink_obj,
        user_specific_settings,
        token
    )

    await message.reply(reply_text)
    # Always delete the deeplink token after it has been processed or attempted to be processed.
    await delete_deeplink_by_token(session, token)
