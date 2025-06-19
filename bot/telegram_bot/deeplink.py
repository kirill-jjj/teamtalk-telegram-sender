import logging
from typing import Callable, Coroutine, Any, Optional
from aiogram import html
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.crud import (
    add_subscriber,
    delete_user_data_fully,
    get_deeplink as db_get_deeplink,
    delete_deeplink_by_token
)
from bot.core.user_settings import (
    UserSpecificSettings,
    get_or_create_user_settings,
    update_user_settings_in_db
)
from bot.core.enums import DeeplinkAction
from bot.database.models import Deeplink # Added for type hinting

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
        await message.reply(_("Invalid or expired deeplink."))  # DEEPLINK_INVALID_OR_EXPIRED
        return None

    if deeplink_obj.expected_telegram_id and deeplink_obj.expected_telegram_id != message_from_user_id:
        await message.reply(_("This confirmation link was intended for a different Telegram account."))  # DEEPLINK_WRONG_ACCOUNT
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
    reply_text = _("An error occurred.")
    action_enum_member: Optional[DeeplinkAction] = None

    try:
        if deeplink_obj.action:
            action_enum_member = DeeplinkAction(str(deeplink_obj.action))
    except ValueError:
        logger.warning(f"Invalid deeplink action string from DB: '{deeplink_obj.action}' for token {token}")
        return _("Invalid deeplink action.") # DEEPLINK_INVALID_ACTION

    if not action_enum_member:
        logger.warning(f"Deeplink action '{deeplink_obj.action}' for token {token} is null or not a valid DeeplinkAction member after attempt to cast.")
        return _("Invalid deeplink action.") # DEEPLINK_INVALID_ACTION

    handler_func = DEEPLINK_ACTION_HANDLERS.get(action_enum_member)
    if not handler_func:
        logger.warning(f"No handler found for DeeplinkAction member: {action_enum_member} from token {token}")
        return _("Invalid deeplink action.") # DEEPLINK_INVALID_ACTION

    try:
        # Adapt calls based on handler signature.
        # This part remains a bit complex due to differing handler needs.
        if action_enum_member == DeeplinkAction.UNSUBSCRIBE:
            reply_text = await handler_func(session, telegram_id, _)
        elif action_enum_member == DeeplinkAction.SUBSCRIBE_AND_LINK_NOON:
            reply_text = await handler_func(session, telegram_id, _, deeplink_obj.payload, user_specific_settings)
        elif action_enum_member == DeeplinkAction.SUBSCRIBE:
            # Assuming payload is not strictly needed or can be None for SUBSCRIBE
            reply_text = await handler_func(session, telegram_id, _, deeplink_obj.payload, user_specific_settings)
        else:
            # Fallback for any other actions that might be added and fit the generic signature
            # Or, this could be an error if all actions must be explicitly handled above.
            # For now, assume they might fit the most general signature.
            logger.info(f"Deeplink action {action_enum_member} called with generic signature.")
            reply_text = await handler_func(session, telegram_id, _, deeplink_obj.payload, user_specific_settings)

    except Exception as e:
        logger.error(f"Error executing deeplink handler for action '{action_enum_member}', token {token}: {e}", exc_info=True)
        reply_text = _("An error occurred.") # ERROR_OCCURRED

    return reply_text


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
        return _("You have successfully subscribed to notifications.") # DEEPLINK_SUBSCRIBED
    return _("You are already subscribed to notifications.") # DEEPLINK_ALREADY_SUBSCRIBED

async def _handle_unsubscribe_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable
) -> str:
    if await delete_user_data_fully(session, telegram_id): # delete_user_data_fully now also clears USER_SETTINGS_CACHE
        logger.info(f"User {telegram_id} unsubscribed and all data was deleted via deeplink.")
        return _("You have successfully unsubscribed from notifications.") # DEEPLINK_UNSUBSCRIBED
    else:
        # This case implies user was not found initially by delete_user_data_fully or deletion failed.
        logger.warning(f"Attempted to unsubscribe user {telegram_id} via deeplink, but user was not found or data deletion otherwise failed.")
        return _("You were not subscribed to notifications.") # DEEPLINK_NOT_SUBSCRIBED


async def _handle_subscribe_and_link_noon_deeplink(
    session: AsyncSession,
    telegram_id: int,
    _: callable,
    payload: str | None,
    user_specific_settings: UserSpecificSettings
) -> str:
    if await add_subscriber(session, telegram_id):
        logger.info(f"User {telegram_id} subscribed via combined deeplink.")
    else:
        logger.info(f"User {telegram_id} was already subscribed, proceeding to link NOON via combined deeplink.")

    current_settings = await get_or_create_user_settings(telegram_id, session)

    tt_username_from_payload = payload
    if not tt_username_from_payload:
        logger.error(f"Deeplink for '{DeeplinkAction.SUBSCRIBE_AND_LINK_NOON}' missing payload for user {telegram_id}.")
        return _("Error: Missing TeamTalk username in confirmation link.") # DEEPLINK_NOON_CONFIRM_MISSING_PAYLOAD

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

    # Always use DEEPLINK_SUBSCRIBED key (English: "You have successfully subscribed to notifications.")
    # This message is generic and doesn't include the username.
    logger.info(f"User {telegram_id} subscribed and NOON linked for TT user {final_tt_username} via combined deeplink. Sending DEEPLINK_SUBSCRIBED message.")
    reply_text = _("You have successfully subscribed to notifications.")
    return reply_text


# Define a type for the handler functions
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

DEEPLINK_ACTION_HANDLERS: dict[DeeplinkAction, Any] = { # Key type changed to DeeplinkAction
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
        await message.reply(_("An error occurred.")) # ERROR_OCCURRED
        return

    message_from_user_id = message.from_user.id

    deeplink_obj = await _validate_deeplink_token(session, token, message_from_user_id, message, _)
    if not deeplink_obj:
        # _validate_deeplink_token already sent the reply and potentially logged.
        # If it returned None due to wrong user, we should not delete the token yet.
        # The current _validate_deeplink_token doesn't delete for wrong user.
        # If it was invalid/expired, deleting it now is fine.
        # To be safe and align with _validate_deeplink_token's current logic,
        # we only delete if the reason for None was not a 'wrong user' scenario.
        # However, the original code deletes it regardless after an attempt.
        # Let's stick to deleting it if deeplink_obj is None after validation,
        # unless _validate_deeplink_token explicitly confirmed it's a "wrong user" case.
        # The current _validate_deeplink_token returns None for "wrong user" without distinction.
        # So, we will delete it here if None, simplifying the logic.
        # If the token was invalid/expired, it's good to delete.
        # If it was for the wrong user, the original code would *not* delete it at that point,
        # but would delete it at the very end. This refactor changes that slightly:
        # if validation fails for *any* reason (incl. wrong user), it's deleted *if* we decide to delete here.
        # Re-evaluating: _validate_deeplink_token handles replies for invalid/wrong user.
        # If it's a wrong user, we should NOT delete the token.
        # If it's invalid/expired, we SHOULD delete.
        # The current _validate_deeplink_token doesn't give us this distinction.
        # For now, let's assume if deeplink_obj is None, _validate_deeplink_token handled the reply,
        # and we decide whether to delete based on a re-fetch or by modifying _validate_deeplink_token.
        # To keep it simple and closer to original end-of-function deletion:
        # if not deeplink_obj, the function returns. The final deletion is outside this block.
        # This means if _validate_deeplink_token returns None, we simply return.
        # The final delete_deeplink_by_token will run if we don't return early.
        # Let's refine: if _validate_deeplink_token returns None, it means a reply was sent. We should just return.
        # The question of deleting the token is separate. The original code deletes it at the end.
        # This means even if it was for the wrong user, it got deleted.
        # Let's preserve that behavior: always try to delete at the end if we reached there.

        # Corrected logic: if _validate_deeplink_token returns None, it means an error reply was sent.
        # We should return, and the final deletion will NOT occur. This is a change from original.
        # If we want to preserve "always delete if processed", then _validate_deeplink_token
        # should not return early but set a flag.
        # Let's stick to the plan: _validate_deeplink_token sends reply and returns None.
        # The main function then returns. This means the token is NOT deleted if validation fails.
        # This is a deviation from the original code's "delete at the end" behavior.
        # To reconcile: The original code's "delete at the end" implies it's deleted even if it was for the wrong user.
        # This seems like the most robust interpretation. So, validation failure should not prevent deletion.

        # Simpler: _validate_deeplink_token handles the reply. We just return.
        # The deletion will be attempted at the end if we don't return from this point.
        # This means if validation fails (e.g. wrong user), we return, and token is NOT deleted.
        # This is probably better than deleting a token meant for another user.
        # If token is invalid/expired, it won't be found by db_get_deeplink again anyway.
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
