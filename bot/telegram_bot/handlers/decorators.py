"""Decorators for Telegram bot handlers."""

from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import Any, TypeVar, cast

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_message_context",
]


F = TypeVar("F", bound=Callable[..., Awaitable[Any | None]])


def ensure_message_context(func: F) -> F:
    """Decorator to ensure that a callback query handler has a message context."""

    @functools.wraps(func)
    async def wrapper(
        query: CallbackQuery,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> Any | None:  # noqa: ANN401
        translator = cast(
            "NullTranslations", kwargs.get("translator", NullTranslations())
        )
        _ = translator.gettext
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
                logger.exception(
                    "Failed to answer callback query in decorator for '%s'.",
                    func.__name__,
                )
            return None

        return await func(query, *args, **kwargs)

    return cast("F", wrapper)
