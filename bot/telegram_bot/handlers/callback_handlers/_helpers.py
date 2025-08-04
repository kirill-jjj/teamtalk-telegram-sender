from collections.abc import Awaitable, Callable
import functools
import gettext
import logging
from typing import TYPE_CHECKING, Any, TypeAlias

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.telegram_bot.callback_data import (
    AdminSetSubscriberLanguageCallback,
    AdminSetSubscriberMuteModeCallback,
    AdminSetSubscriberNotificationPrefCallback,
    SubscriberActionCallback,
)
from bot.telegram_bot.ui_utils import safe_edit_text  # Import safe_edit_text from its new location

from ._view_rendering import _display_subscriber_view

if TYPE_CHECKING:
    from bot.services_container import Services


logger = logging.getLogger(__name__)

__all__ = [
    "action_and_refresh_subscriber_view",
    "ensure_message_context",
    "safe_edit_text",
]

RefreshableViewCallback: TypeAlias = (
    AdminSetSubscriberLanguageCallback
    | AdminSetSubscriberNotificationPrefCallback
    | AdminSetSubscriberMuteModeCallback
    | SubscriberActionCallback
)


def action_and_refresh_subscriber_view(
    func: Callable[..., Awaitable[tuple[bool, str]]]
) -> Callable[..., Awaitable[None]]:
    """Decorator for admin actions on a subscriber that results in refreshing the subscriber view.

    - It calls the wrapped handler, which should perform an action and return a (success, message) tuple.
    - It answers the callback query with the message.
    - It refreshes the subscriber detail view.
    """

    @functools.wraps(func)
    async def wrapper(
        query: CallbackQuery,
        callback_data: RefreshableViewCallback,
        session: AsyncSession,
        translator: gettext.GNUTranslations,
        services: "Services",
        **kwargs: object,
    ) -> None:
        # The @ensure_message_context decorator should be applied before this one,
        # so we can assume query.message is not None.

        # 1. Call the wrapped handler to perform the core action
        success, message = await func(
            query=query,
            callback_data=callback_data,
            session=session,
            translator=translator,
            services=services,
            **kwargs,
        )

        # 2. Answer the callback query with the result message
        await query.answer(message, show_alert=not success)

        # 3. Refresh the subscriber view
        target_telegram_id = callback_data.target_telegram_id

        # The page context attribute can have different names in different callbacks.
        if hasattr(callback_data, "subscriber_page_context"):
            page_context = callback_data.subscriber_page_context
        elif hasattr(callback_data, "page"):
            page_context = callback_data.page
        else:
            logger.warning(
                "Could not determine page context from callback_data for handler '%s'. Defaulting to page 0.",
                func.__name__,
            )
            page_context = 0

        # Call the view rendering function to refresh the UI
        await _display_subscriber_view(
            query=query,
            target_telegram_id=target_telegram_id,
            page_context=page_context,
            session=session,
            translator=translator,
            services=services,
        )

    return wrapper


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
