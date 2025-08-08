"""Decorators for Telegram bot handlers."""

from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import Any, Protocol, TypeVar, cast

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_message_context",
    "ensure_tt_user_exists",
]


F = TypeVar("F", bound=Callable[..., Awaitable[Any | None]])


def ensure_message_context(func: F) -> F:
    """Decorator to ensure that a callback query handler has a message context."""

    @functools.wraps(func)
    async def wrapper(query: CallbackQuery, *args: Any, **kwargs: Any) -> Any | None:
        translator = cast(
            NullTranslations, kwargs.get("translator", NullTranslations())
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

    return cast(F, wrapper)


def ensure_tt_user_exists(func: F) -> F:
    """Decorator to ensure that a TeamTalk user from a callback query exists."""

    class CallbackWithUserId(Protocol):
        user_id: int

    T = TypeVar("T", bound=CallbackWithUserId)

    @functools.wraps(func)
    async def wrapper(
        query: CallbackQuery,
        callback_data: T,
        translator: NullTranslations,
        tt_connection: TeamTalkConnection,
        *args: Any,
        **kwargs: Any,
    ) -> Any | None:
        _ = translator.gettext

        if not tt_connection.instance:
            logger.error("Handler '%s': tt_connection has no instance.", func.__name__)
            await query.answer(
                _("Error: No active TeamTalk connection."), show_alert=True
            )
            return None

        server_host = tt_connection.server_info.host
        user_to_act_on = tt_connection.instance.get_user(callback_data.user_id)

        if not user_to_act_on:
            await query.answer(
                _("User not found on server {server_host} anymore.").format(
                    server_host=server_host
                ),
                show_alert=True,
            )
            if query.message and isinstance(query.message, Message):
                try:
                    await query.message.edit_reply_markup(reply_markup=None)
                except TelegramAPIError:
                    logger.debug(
                        "Failed to remove reply markup when user %s was not found on %s.",
                        callback_data.user_id,
                        server_host,
                    )
            return None

        kwargs["tt_user"] = user_to_act_on
        # Pass all original and new kwargs to the decorated function
        return await func(
            query, callback_data, translator, tt_connection, *args, **kwargs
        )

    return cast(F, wrapper)
