import logging
from typing import Callable, Optional
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from bot.models import UserSettings
from bot.core.user_settings import update_user_settings_in_db

logger = logging.getLogger(__name__)

async def process_setting_update(
    callback_query: CallbackQuery,
    session: AsyncSession,
    user_settings: UserSettings,
    _: callable,
    update_action: Callable[[], None],
    revert_action: Callable[[], None],
    success_toast_text: str,
    new_text: str,
    new_markup: InlineKeyboardMarkup
) -> None:
    # Ensure message and from_user are present, crucial for callback context
    if not callback_query.message or not callback_query.from_user:
        logger.warning("process_setting_update: Callback query is missing message or from_user.")
        # Try to answer callback even if message context is faulty, to acknowledge interaction
        try:
            await callback_query.answer(_("Error: Callback query is missing essential data."), show_alert=True)
        except TelegramAPIError as ans_err_crit: # Catch if even answering fails
            logger.error(f"Critical error: Failed to answer callback for missing data: {ans_err_crit}")
        return

    update_action() # Apply change in-memory first

    try:
        await update_user_settings_in_db(session, user_settings)
        # Send toast only on successful DB update
        await callback_query.answer(success_toast_text, show_alert=False)

        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=new_text,
            reply_markup=new_markup,
            logger_instance=logger,
            log_context="process_setting_update_ui_refresh"
        )

    except SQLAlchemyError as e_db:
        logger.error(f"Failed to update settings in DB for user {callback_query.from_user.id}. Error: {e_db}", exc_info=True)
        revert_action() # Revert in-memory change
        try:
            await callback_query.answer(_("An error occurred."), show_alert=True)
        except TelegramAPIError as ans_err_revert:
            logger.warning(f"Could not send error alert for DB update failure/revert: {ans_err_revert}")
        # Do not proceed to UI refresh if DB update failed
        return

    except TelegramAPIError as e_tg:
        # This error can occur during answer() or safe_edit_text() if the user blocked the bot
        # after settings were successfully saved to the DB.
        # Since data is already saved, we log the error. No rollback needed here.
        logger.warning(
            f"Telegram API error during UI update for user {callback_query.from_user.id} "
            f"after settings were saved. Error: {e_tg}"
        )


async def safe_edit_text(
    message_to_edit: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: Optional[bool] = None,
    logger_instance: Optional[logging.Logger] = None,
    log_context: str = ""
) -> bool:
    """
    Safely edits a message text, handling common Telegram API errors.

    Args:
        message_to_edit: The aiogram.types.Message object to edit.
        text: New text of the message.
        reply_markup: Optional inline keyboard markup.
        parse_mode: Optional parse mode for the text.
        disable_web_page_preview: Optional bool to disable link previews.
        logger_instance: Optional logger instance. If None, uses the module's logger.
        log_context: Optional context string for error logging.

    Returns:
        True if the message was edited successfully or if the error was "message is not modified".
        False for other TelegramAPIError or unexpected errors.
    """
    current_logger = logger_instance or logger
    context_for_log = f" ({log_context})" if log_context else ""

    try:
        await message_to_edit.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview
        )
        return True
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            current_logger.error(f"TelegramBadRequest editing message{context_for_log}: {e}", exc_info=True)
            return False # Explicitly return False for handled errors other than "not modified"
        return True # "Message not modified" is considered a success in terms of state
    except TelegramAPIError as e:
        current_logger.error(f"TelegramAPIError editing message{context_for_log}: {e}", exc_info=True)
        return False
