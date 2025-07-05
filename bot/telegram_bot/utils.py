import logging
import asyncio
import pytalk
from typing import Callable
from aiogram import Bot
from aiogram import Bot as AiogramBot # ДОБАВЬ ЭТУ СТРОКУ
from aiogram.types import InlineKeyboardMarkup, Message, CallbackQuery, Chat
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError, TelegramBadRequest
from sqlalchemy.exc import SQLAlchemyError

# from bot.config import app_config # Not used directly here anymore
from bot.services import user_service # Keep, used by _handle_telegram_api_error
# from bot.database.engine import SessionFactory # No longer directly used, app.session_factory is used
# from bot.core.user_settings import USER_SETTINGS_CACHE # No longer directly used, app.user_settings_cache is used
# from bot.state import ONLINE_USERS_CACHE # Removed
from bot.constants import (
    DEFAULT_LANGUAGE,
)
# from bot.telegram_bot.bot_instances import tg_bot_event, tg_bot_message # Bot instances passed as params

# For type hinting app instance
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sender import Application

ttstr = pytalk.instance.sdk.ttstr
logger = logging.getLogger(__name__)


async def _handle_telegram_api_error(error: TelegramAPIError, chat_id: int, app: "Application"): # app is now a direct param
    """
    Handles specific Telegram API errors.
    """
    if not app: # Should ideally not happen if called correctly
        logger.error(f"Telegram API error for chat_id {chat_id} but app context was missing for full cleanup: {error}")
        return

    if isinstance(error, TelegramForbiddenError):
        if "bot was blocked by the user" in str(error).lower() or "user is deactivated" in str(error).lower():
            logger.warning(f"User {chat_id} blocked the bot or is deactivated. Deleting all user data...")
            try:
                async with app.session_factory() as session: # Use app's session_factory
                    success = await user_service.delete_full_user_profile(session, chat_id, app=app)
                if success:
                    logger.info(f"Successfully deleted all data for blocked/deactivated user {chat_id}.")
                else:
                    logger.error(f"Failed to delete data for blocked/deactivated user {chat_id}, though an attempt was made.")
            except SQLAlchemyError as db_err:
                logger.error(f"Failed to delete data for blocked/deactivated user {chat_id} from DB: {db_err}")
        else:
            logger.error(f"Telegram API Forbidden error for chat_id {chat_id}: {error}")

    elif isinstance(error, TelegramBadRequest):
        if "chat not found" in str(error).lower():
            logger.warning(f"Chat not found for TG ID {chat_id}. Assuming user is gone. Deleting all user data. Error: {error}")
            try:
                async with app.session_factory() as session: # Use app's session_factory
                    delete_success = await user_service.delete_full_user_profile(session, chat_id, app=app)
                if delete_success:
                    logger.info(f"Successfully deleted all data for TG ID {chat_id} due to chat not found.")
                else:
                    logger.error(f"Failed to delete all data for TG ID {chat_id} after chat not found.")
            except SQLAlchemyError as db_cleanup_err:
                logger.error(f"Exception during full data cleanup for TG ID {chat_id} (chat not found): {db_cleanup_err}")
        else:
            logger.error(f"Telegram API BadRequest (non 'chat not found') for chat_id {chat_id}: {error}")

    elif isinstance(error, TelegramAPIError):
        logger.error(f"Unhandled Telegram API error for chat_id {chat_id}: {error}")


def _should_send_silently(chat_id: int, tt_user_is_online: bool, app: "Application") -> bool:
    """
    Checks if a message to a given chat_id should be sent silently based on
    NOON settings and the provided online status of their linked TeamTalk user.
    Uses app.user_settings_cache.
    """
    recipient_settings = app.user_settings_cache.get(chat_id)

    if (
        recipient_settings and
        recipient_settings.not_on_online_enabled and
        recipient_settings.not_on_online_confirmed and
        tt_user_is_online # Directly use the passed boolean
    ):
        logger.debug(f"Message to {chat_id} will be silent: linked user is online and NOON is enabled.")
        return True

    return False


async def send_telegram_message_individual(
    bot_instance: Bot,
    chat_id: int,
    app: "Application", # Changed to non-optional
    language: str = DEFAULT_LANGUAGE,
    reply_markup: InlineKeyboardMarkup | None = None,
    tt_user_is_online: bool = False,
    **kwargs
) -> bool:
    # app is now mandatory
    send_silently = _should_send_silently(chat_id, tt_user_is_online, app)

    try:
        await bot_instance.send_message(
            chat_id=chat_id,
            reply_markup=reply_markup,
            disable_notification=send_silently,
            **kwargs
        )
        logger.debug(f"Message sent to {chat_id}. Silent: {send_silently}, kwargs used: {kwargs}")
        return True
    except TelegramAPIError as e:
        await _handle_telegram_api_error(e, chat_id, app=app) # Pass app to error handler
        return False


async def send_telegram_messages_to_list(
    bot_instance_to_use: AiogramBot, # Renamed Bot to AiogramBot
    chat_ids: list[int],
    text_generator: Callable[[str], str],
    user_settings_cache: dict, # Expect app.user_settings_cache
    # session_factory: "DbSessionFactory", # No longer needed directly by this func, but by _handle_telegram_api_error via app
    app: "Application", # Pass Application instance
    online_users_cache_for_instance: Optional[dict[int, TeamTalkUser]] = None, # For specific instance's online users
    reply_markup_generator: Callable[[str, int], InlineKeyboardMarkup | None] | None = None
):
    if not bot_instance_to_use:
        logger.error("No Telegram bot instance provided to send_telegram_messages_to_list.")
        return

    tasks_list = []
    for chat_id in chat_ids:
        user_settings = user_settings_cache.get(chat_id) # Use passed user_settings_cache
        language_code = user_settings.language_code if user_settings else DEFAULT_LANGUAGE
        text = text_generator(language_code)
        current_reply_markup = reply_markup_generator(language_code, chat_id) if reply_markup_generator else None

        individual_tt_user_is_online = False
        if user_settings and user_settings.teamtalk_username and online_users_cache_for_instance:
            # Check if the recipient's linked TT username is in the provided online cache for the relevant instance
            # The key for online_users_cache_for_instance is user_id (int), value is User object.
            # We need to iterate values to check by username if not already a set of usernames.
            for tt_user_obj in online_users_cache_for_instance.values():
                if ttstr(tt_user_obj.username) == user_settings.teamtalk_username:
                    individual_tt_user_is_online = True
                    break

        tasks_list.append(send_telegram_message_individual(
            bot_instance=bot_instance_to_use,
            chat_id=chat_id,
            language=language_code,
            reply_markup=current_reply_markup,
            tt_user_is_online=individual_tt_user_is_online,
            app=app, # Pass app context down
            text=text,
            parse_mode="HTML"
        ))
    await asyncio.gather(*tasks_list)


async def send_or_edit_paginated_list(
    target: "Message | CallbackQuery", # type: ignore
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    bot: Bot | None = None, # Required if target is Message, for reply
    **kwargs
) -> None:
    """
    Sends a new message or edits an existing one with paginated content.

    :param target: The aiogram Message or CallbackQuery object.
    :param text: The text content for the message.
    :param reply_markup: The InlineKeyboardMarkup for the message.
    :param bot: The Bot instance, required if target is a Message.
    :param kwargs: Additional arguments to pass to send_message or edit_message_text.
    """
    answered_with_alert = False
    if hasattr(target, 'message') and target.message: # Handles CallbackQuery
        try:
            await target.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                **kwargs
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                logger.debug(f"Message not modified for chat_id {target.message.chat.id}, skipping edit.")
                # Try to answer the callback query to remove the "loading" state
                if hasattr(target, 'answer'):
                    try:
                        await target.answer()
                    except Exception as answer_e: # Could be already answered
                        logger.warning(f"Failed to answer CbQ after 'message not modified': {answer_e}")
            else: # Other TelegramBadRequest
                logger.error(f"Error editing message for chat_id {target.message.chat.id}: {e}", exc_info=True)
                if hasattr(target, 'answer'):
                    try:
                        await target.answer("Error updating list.", show_alert=True) # type: ignore
                        answered_with_alert = True
                    except Exception as answer_e:
                        logger.warning(f"Failed to answer CbQ with alert after edit error: {answer_e}")
        except Exception as e: # Other errors during edit
            logger.error(f"Generic error editing message for chat_id {target.message.chat.id}: {e}", exc_info=True)
            if hasattr(target, 'answer'):
                try:
                    await target.answer("Error updating list.", show_alert=True) # type: ignore
                    answered_with_alert = True
                except Exception as answer_e:
                    logger.warning(f"Failed to answer CbQ with alert after generic edit error: {answer_e}")

    elif hasattr(target, 'reply') and bot: # Handles Message
        if target: # Ensure target (Message object) is not None
            try:
                await target.reply(
                    text=text,
                    reply_markup=reply_markup,
                    **kwargs
                )
            except Exception as e: # Catch potential errors during reply
                logger.error(f"Error replying to message for chat_id {target.chat.id}: {e}", exc_info=True)
        else:
            logger.error("Attempted to reply to a None message object.")

    else:
        logger.error(
            "Invalid target type for send_or_edit_paginated_list. "
            "Must be Message or CallbackQuery. If Message, bot instance must be provided."
        )

    # If it's a CbQ and edit was successful (or not modified) and we haven't shown an alert
    if hasattr(target, 'answer') and not answered_with_alert:
        try:
            # This might fail if already answered by the "message not modified" block, which is fine.
            await target.answer() # type: ignore
        except TelegramAPIError as e:
            cbq_id = target.id if hasattr(target, 'id') else 'N/A'
            if "query is too old" in str(e).lower() or "query id is invalid" in str(e).lower():
                logger.debug(f"CbQ {cbq_id} likely already answered or too old.")
            else:
                logger.warning(f"Failed to answer CbQ {cbq_id} at the end of send_or_edit: {e}")
        except Exception as e:
            cbq_id = target.id if hasattr(target, 'id') else 'N/A'
            logger.warning(f"Generic error answering CbQ {cbq_id} at the end of send_or_edit: {e}")


def format_telegram_user_display_name(chat: Chat | None) -> str:
    """
    Formats a Telegram user's display name from a Chat object.
    Returns the Telegram ID as a string if chat object is None or no other info is available.
    """
    if not chat:
        # Fallback for cases where chat might be None, though ideally it's always provided.
        # Returning "N/A" or an empty string might be alternatives.
        # For now, let's assume if chat is None, we can't get an ID either, so "Unknown User".
        # However, the original code defaults to telegram_id if chat fetch fails.
        # This function expects a Chat object. If it can be None, the caller should handle it
        # or this function needs a way to get an ID (e.g., pass telegram_id as fallback).
        # Given the usage context, chat object is usually available.
        # If chat is None, and we are *only* passed chat, we cannot return chat.id.
        # Let's stick to the logic: if chat is None, we can't process it.
        return "Unknown User" # Or raise an error, or handle as per specific app logic.

    # Default to string representation of chat.id if no other name parts are available
    display_name = str(chat.id)

    # Try to construct a more descriptive name
    full_name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
    username_part = f" (@{chat.username})" if chat.username else ""

    if full_name:
        display_name = f"{full_name}{username_part}"
    elif chat.username: # Only username is available
        display_name = f"@{chat.username}"
    # If neither full_name nor username is present, display_name remains str(chat.id)

    return display_name


async def safe_delete_message(message: Message, log_context_message: str = "message") -> bool:
    """
    Safely deletes a message, catching TelegramAPIErrors and logging them.

    :param message: The aiogram.types.Message object to delete.
    :param log_context_message: A string to include in the log message for context
                                (e.g., "user settings command", "user menu command").
    :return: True if deletion was successful or if the message was already deleted/not found,
             False if another TelegramAPIError occurred.
    """
    try:
        await message.delete()
        return True
    except TelegramBadRequest as e:
        # Specific check for errors indicating the message can't be deleted because it's too old,
        # doesn't exist, or the bot doesn't have rights. These are often not critical failures
        # for the calling function's flow.
        if "message to delete not found" in str(e).lower() or \
           "message can't be deleted" in str(e).lower() or \
           "message identifier is not specified" in str(e).lower(): # Should not happen with Message obj
            logger.info(f"Could not delete {log_context_message} (message likely already gone or permissions issue): {e}")
            return True # Treat as "handled" or "not an issue for caller"
        else:
            logger.warning(f"TelegramBadRequest when trying to delete {log_context_message}: {e}")
            return False # Other bad requests might be more problematic
    except TelegramAPIError as e:
        # Catches other errors like Forbidden, etc.
        logger.warning(f"Could not delete {log_context_message} due to TelegramAPIError: {e}")
        return False
    except Exception as e:
        # Catch any other unexpected error
        logger.error(f"Unexpected error when trying to delete {log_context_message}: {e}", exc_info=True)
        return False