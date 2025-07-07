from collections.abc import Callable
import functools
import logging
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession  # Added this based on usage

from bot.core.user_settings import update_user_settings_in_db
from bot.models import UserSettings

if TYPE_CHECKING:
    from bot.services_container import Services

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
    new_markup: InlineKeyboardMarkup,
    services: "Services",
) -> None:
    if not callback_query.message or not callback_query.from_user:
        logger.warning("process_setting_update: Callback query is missing message or from_user.")
        try:
            # Assuming _ is available in this scope for the error message
            await callback_query.answer(_("Error: Callback query is missing essential data."), show_alert=True)
        except TelegramAPIError as ans_err_crit:
            logger.error("Critical error: Failed to answer callback for missing data: %s", ans_err_crit)
        return

    update_action()

    try:
        await update_user_settings_in_db(session, user_settings)
        services.user_settings_cache[user_settings.telegram_id] = user_settings
        await callback_query.answer(success_toast_text, show_alert=False)

        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=new_text,
            reply_markup=new_markup,
            logger_instance=logger,
            log_context="process_setting_update_ui_refresh",
        )

    except SQLAlchemyError as e_db:
        logger.exception(
            "Failed to update settings in DB for user %s. Error: %s",
            callback_query.from_user.id,
            e_db,
        )
        revert_action()
        try:
            # Assuming _ is available
            await callback_query.answer(_("An error occurred. Please try again later."), show_alert=True)
        except TelegramAPIError as ans_err_revert:
            logger.warning("Could not send error alert for DB update failure/revert: %s", ans_err_revert)
        return

    except TelegramAPIError as e_tg:
        logger.warning(
            "Telegram API error during UI update for user %s after settings were saved. Error: %s",
            callback_query.from_user.id,
            e_tg,
        )


async def safe_edit_text(
    message_to_edit: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool | None = None,
    logger_instance: logging.Logger | None = None,
    log_context: str = "",
) -> bool:
    """Safely edits a message text, handling common Telegram API errors."""
    current_logger = logger_instance or logger
    context_for_log = f" ({log_context})" if log_context else ""

    try:
        await message_to_edit.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
        return True
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            current_logger.exception("TelegramBadRequest editing message%s: %s", context_for_log, e)
            return False
        return True
    except TelegramAPIError as e:
        current_logger.exception("TelegramAPIError editing message%s: %s", context_for_log, e)
        return False


# Decorator for checking query.message context
def ensure_message_context(func: Callable):
    """Decorator to ensure that a callback query handler has a message context.

    If query.message is None, it logs an error and attempts to answer the callback query.
    """

    @functools.wraps(func)
    async def wrapper(query: CallbackQuery, *args, **kwargs):
        if not query.message:
            translator_func = None
            if "translator" in kwargs:
                translator_instance = kwargs["translator"]
                if hasattr(translator_instance, "gettext"):
                    translator_func = translator_instance.gettext
                elif callable(translator_instance):
                    translator_func = translator_instance
            elif "_" in kwargs:
                translator_instance = kwargs["_"]
                if callable(translator_instance):
                    translator_func = translator_instance

            error_message = "Error: Message context lost for callback query."
            if translator_func:
                try:
                    error_message = translator_func("Error processing command.")
                except TypeError as te:
                    logger.exception(
                        "Translator function not callable or wrong arguments in decorator for %s: %s",
                        func.__name__,
                        te,
                    )
                except Exception as e:
                    logger.exception("Failed to translate error message in decorator for %s: %s", func.__name__, e)
            else:
                logger.warning(
                    "Translator function not found for handler %s, using default error message.", func.__name__
                )

            logger.error(
                "Handler %s: query.message is None. Callback data: %s. User: %s",
                func.__name__,
                query.data,
                query.from_user.id,
            )
            try:
                await query.answer(error_message, show_alert=True)
            except TelegramAPIError as e:
                logger.error("Failed to answer callback query in decorator for %s: %s", func.__name__, e)
            return None

        return await func(query, *args, **kwargs)

    return wrapper
