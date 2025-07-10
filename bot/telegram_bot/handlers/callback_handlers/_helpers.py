from collections.abc import Awaitable, Callable
import functools
import gettext
import logging
from typing import TYPE_CHECKING, Any

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

from bot.telegram_bot.ui_utils import safe_edit_text  # Import safe_edit_text from its new location

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_message_context",
    # "process_setting_update", # Removed
    "safe_edit_text", # Note: safe_edit_text is imported from ui_utils, then re-exported here.
]

# process_setting_update function definition removed.


# safe_edit_text MOVED to bot/telegram_bot/ui_utils.py


def ensure_message_context(
    func: Callable[..., Awaitable[Any | None]],
) -> Callable[..., Awaitable[Any | None]]:
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
