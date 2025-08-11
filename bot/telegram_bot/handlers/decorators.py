"""Decorators for Telegram bot handlers."""

from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import Any, Protocol, TypeAlias, TypeVar, cast

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from bot.models import UserSettings
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    SubscriberCallback,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_message_context",
    "ensure_tt_user_exists",
    "require_tt_connection",
    "with_view_refresh",
]


RefreshableViewCallback: TypeAlias = (
    AdminSetSubscriberLanguageCallback
    | AdminSetSubscriberNotificationPrefCallback
    | AdminSetSubscriberMuteModeCallback
    | SubscriberCallback
)


ViewRefresher: TypeAlias = Callable[..., Awaitable[None]]


def with_view_refresh(
    view_refresher: ViewRefresher,
) -> Callable[
    [Callable[..., Awaitable[tuple[bool, str, Any | None]]]],
    Callable[..., Awaitable[None]],
]:
    """Decorator factory for actions that result in refreshing a view.

    The decorated function MUST return a tuple: (success, message, updated_object).
    """

    def decorator(
        func: Callable[..., Awaitable[tuple[bool, str, Any | None]]],
    ) -> Callable[..., Awaitable[None]]:
        @functools.wraps(func)
        async def wrapper(
            query: CallbackQuery,
            *args: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> None:
            """Wrapper function for the with_view_refresh decorator."""
            # Call the original handler function
            success, message, updated_object = await func(query, *args, **kwargs)

            # Manually answer the callback query
            if message:  # Answer with a message if one was provided
                await query.answer(text=message, show_alert=not success)
            else:  # Otherwise, just acknowledge the callback
                await query.answer()

            # The rest of the logic for refreshing the view
            if updated_object and isinstance(updated_object, UserSettings):
                kwargs["user_settings"] = updated_object
                if "translator_factory" in kwargs:
                    translator_factory = kwargs["translator_factory"]
                    new_translator = translator_factory(updated_object.language_code)
                    kwargs["translator"] = new_translator

            if "callback_data" not in kwargs and args:
                for arg in args:
                    if isinstance(arg, RefreshableViewCallback):
                        kwargs["callback_data"] = arg
                        break

            await view_refresher(
                query,
                *args,
                **kwargs,
            )

        return wrapper

    return decorator


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


def require_tt_connection(func: F) -> F:
    """Decorator to ensure that a TeamTalk connection is active."""

    @functools.wraps(func)
    async def wrapper(
        message_or_query: Message | CallbackQuery,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> Any | None:  # noqa: ANN401
        translator = cast(
            NullTranslations, kwargs.get("translator", NullTranslations())
        )
        tt_connection = cast(
            TeamTalkConnection | None, kwargs.get("tt_connection")
        )
        _ = translator.gettext

        if not tt_connection:
            reply_target = (
                message_or_query
                if isinstance(message_or_query, Message)
                else message_or_query.message
            )
            if reply_target:
                await reply_target.reply(_("TeamTalk connection is not active."))
            if isinstance(message_or_query, CallbackQuery):
                await message_or_query.answer()
            return None

        return await func(message_or_query, *args, **kwargs)

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
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> Any | None:  # noqa: ANN401
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
                        "Failed to remove reply markup for user %s on server %s.",
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
