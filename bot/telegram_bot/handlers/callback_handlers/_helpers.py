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


# Decorator for checking query.message context
import functools

def ensure_message_context(func: Callable):
    """
    Decorator to ensure that a callback query handler has a message context.
    If query.message is None, it logs an error and attempts to answer the callback query.
    """
    @functools.wraps(func)
    async def wrapper(query: CallbackQuery, *args, **kwargs):
        if not query.message:
            # Try to get a translator instance from args or kwargs
            # Common names are '_', 'translator', 'l10n'
            translator_func = None
            # Check kwargs first as they are explicit
            if 'translator' in kwargs:
                translator_instance = kwargs['translator']
                if hasattr(translator_instance, 'gettext'):
                    translator_func = translator_instance.gettext
                elif callable(translator_instance): # If it's already gettext itself
                    translator_func = translator_instance
            elif '_' in kwargs: # Check for common alias '_'
                 translator_instance = kwargs['_']
                 if callable(translator_instance): # Assuming _ is gettext
                     translator_func = translator_instance

            # If not in kwargs, check positional args. This is more fragile.
            # This requires knowing the typical position of the translator/gettext function.
            # For this bot, `_` or `translator` is often the last or second to last of the specific args
            # before `session`, `bot`, `tt_instance` which are often injected.
            # Let's assume for `menu_callbacks.py` it might be the `translator` kwarg or `_` kwarg.
            # If a handler doesn't have translator in its signature, this won't find it.
            # Most menu_callbacks.py handlers use `translator: "gettext.GNUTranslations"`
            # or `_: callable` (which is `translator.gettext`).

            # Simplified: Try to find `_` or `translator` in kwargs.
            # If the handler uses positional args for these, this needs adjustment or handlers need standardization.
            # The `menu_callbacks.py` handlers mostly use `translator` or `_` as keyword args due to type hints.

            error_message = "Error: Message context lost for callback query."
            if translator_func:
                try:
                    error_message = translator_func("Error processing command.") # Generic error from menu_callbacks
                except Exception as e:
                    logger.error(f"Failed to translate error message in decorator: {e}")
            else: # Fallback if no translator found
                logger.warning(f"Translator function not found for handler {func.__name__}, using default error message.")


            logger.error(
                f"Handler {func.__name__}: query.message is None. Callback data: {query.data}. User: {query.from_user.id}"
            )
            try:
                await query.answer(error_message, show_alert=True)
            except TelegramAPIError as e:
                logger.error(f"Failed to answer callback query in decorator for {func.__name__}: {e}")
            return None # Stop execution of the wrapped function

        return await func(query, *args, **kwargs)
    return wrapper
