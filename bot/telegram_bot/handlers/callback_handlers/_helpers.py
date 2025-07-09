from collections.abc import Awaitable, Callable  # Added Awaitable
import functools
import gettext
import logging
from typing import TYPE_CHECKING, Any  # Added Any

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.user_settings import update_user_settings_in_db
from bot.models import UserSettings
from bot.telegram_bot.ui_utils import safe_edit_text  # Import safe_edit_text from its new location

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


async def process_setting_update(  # Added return type hint
    callback_query: CallbackQuery,
    session: AsyncSession,
    user_settings: UserSettings,
    translator: gettext.GNUTranslations,  # Changed from _: callable
    update_action: Callable[[], None],
    revert_action: Callable[[], None],
    success_toast_text: str,
    new_text: str,
    new_markup: InlineKeyboardMarkup,
    services: "Services",
) -> None:  # Added return type hint
    _ = translator.gettext

    if not callback_query.from_user:
        logger.warning("process_setting_update: Callback query is missing from_user.")
        try:
            await callback_query.answer(_("Error: Callback query is missing user data."), show_alert=True)
        except TelegramAPIError:
            logger.exception("Critical error: Failed to answer callback for missing user data.")
        return

    if not isinstance(callback_query.message, Message):
        logger.warning(
            "process_setting_update: Callback query message is None or inaccessible for user %s. Callback data: %s. "
            "Settings will be updated, but UI may not refresh.",
            callback_query.from_user.id,
            callback_query.data,
        )
        # Attempt to update settings anyway, then answer callback, then return.
        update_action()
        try:
            await update_user_settings_in_db(session, user_settings)
            services.cache.update_user_settings(user_settings)
            await callback_query.answer(success_toast_text, show_alert=False)  # Inform success of setting change
        except SQLAlchemyError:
            logger.exception(
                "Failed to update settings in DB for user %s (message inaccessible path).",
                callback_query.from_user.id,
            )
            revert_action()  # Revert in-memory change
            try:
                await callback_query.answer(
                    _("An error occurred updating settings. Please try again."), show_alert=True
                )
            except TelegramAPIError:
                logger.exception("Failed to answer callback for DB error (message inaccessible path).")
        except TelegramAPIError:  # For the answer itself
            logger.exception("Failed to answer callback after settings update (message inaccessible path).")
        return  # Stop before trying to edit the message

    # If we reach here, callback_query.message is a valid Message object
    update_action()

    try:
        await update_user_settings_in_db(session, user_settings)
        services.cache.update_user_settings(user_settings)
        await callback_query.answer(success_toast_text, show_alert=False)

        await safe_edit_text(
            message_to_edit=callback_query.message,
            text=new_text,
            reply_markup=new_markup,
            logger_instance=logger,
            log_context="process_setting_update_ui_refresh",
        )

    except SQLAlchemyError:
        logger.exception(
            "Failed to update settings in DB for user %s.",
            callback_query.from_user.id,
        )
        revert_action()
        try:
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


# safe_edit_text MOVED to bot/telegram_bot/ui_utils.py


def ensure_message_context(
    func: Callable[..., Awaitable[Any | None]],  # Changed signature
) -> Callable[..., Awaitable[Any | None]]:  # Changed signature
    """Decorator to ensure that a callback query handler has a message context.

    If query.message is None, it logs an error and attempts to answer the callback query.
    """

    @functools.wraps(func)
    async def wrapper(
        query: CallbackQuery,  # Keep query as first arg for clarity in wrapper
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> Any | None:  # noqa: ANN401
        # I18nMiddleware is expected to inject 'translator' into kwargs
        translator = kwargs.get("translator")

        if not isinstance(translator, gettext.GNUTranslations):
            # This is an unexpected situation if middlewares are correctly configured.
            logger.critical(
                "Translator object not found or not a GNUTranslations instance in handler '%s' context! "
                "Check middleware order/injection. Falling back to NullTranslations.",
                func.__name__,
            )
            translator = gettext.NullTranslations()

        _ = translator.gettext

        # This message is specifically for the case where query.message is None
        error_message_for_missing_context = _("Error processing command.")

        if not query.message:
            logger.error(
                "Handler '%s': query.message is None. Callback data: %s. User ID: %s",
                func.__name__,
                query.data,
                query.from_user.id,
            )
            try:
                await query.answer(error_message_for_missing_context, show_alert=True)
            except TelegramAPIError:
                logger.exception("Failed to answer callback query in decorator for '%s'.", func.__name__)
            return None  # Stop further execution of the handler

        return await func(query, *args, **kwargs)

    return wrapper
