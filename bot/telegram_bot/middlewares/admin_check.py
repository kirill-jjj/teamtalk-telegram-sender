"""Middleware to check if a Telegram user is an administrator."""

from collections.abc import Awaitable, Callable
import gettext  # For translator type hint
import logging

# For type hinting
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from aiogram.types import User as AiogramUser

if TYPE_CHECKING:
    pass  # Import Services

logger = logging.getLogger(__name__)


class AdminCheckMiddleware(BaseMiddleware):
    """This middleware checks if the user who triggered a command or pressed a button is an administrator.

    Relies on 'event_from_user', 'services' (for CacheService), and 'translator' being in workflow_data.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:  # noqa: ANN401
        """Executes the middleware.

        Checks if the user is an admin. If not, and the event is a CallbackQuery or Message,
        it sends an unauthorized message and stops processing. Otherwise, allows admin users
        or unhandled event types to proceed.

        Args:
            handler: The next handler in the chain.
            event: The incoming Telegram event.
            data: Data to be passed to the handler.

        Returns:
            The result of the next handler if authorized, or None if unauthorized.
        """
        user: AiogramUser | None = data.get("event_from_user")
        if not user:
            logger.debug("AdminCheckMiddleware: No 'event_from_user' in data. Skipping check.")
            return await handler(event, data)

        services = data.get("services")
        if not services:
            logger.critical("AdminCheckMiddleware: 'services' not found in data. Cannot perform admin check.")
            # Optionally, send a generic error message to the user before returning
            # This situation should ideally not happen if middlewares are set up correctly.
            return None  # Or raise an exception

        if not services.cache.is_admin(user.id):
            # I18nMiddleware runs before this, so 'translator' is guaranteed to be in data.
            current_translator: gettext.GNUTranslations | gettext.NullTranslations = data["translator"]
            _ = current_translator.gettext
            unauthorized_message = _("You are not authorized to perform this action.")

            if isinstance(event, CallbackQuery):
                await event.answer(unauthorized_message, show_alert=True)
                logger.warning(
                    "Unauthorized access denied for user %s (Username: %s) in CallbackQuery to event: %s.",
                    user.id,
                    user.username,
                    type(event).__name__,
                )
                return None  # Stop processing

            if isinstance(event, Message):
                await event.reply(unauthorized_message)
                logger.warning(
                    "Unauthorized access denied for user %s (Username: %s) in Message handler for command: %s.",
                    user.id,
                    user.username,
                    event.text,
                )
                return None  # Stop processing

            logger.warning(
                "AdminCheckMiddleware: Unauthorized user %s (Username: %s) "
                "for unhandled event type %s. Behavior for this event type is undefined.",
                user.id,
                user.username,
                type(event).__name__,
            )
            # Depending on policy, you might want to stop processing here too, or let it pass.
            # For safety, let's stop it.
            return None

        logger.debug(
            "AdminCheckMiddleware: User %s (Username: %s) authorized. Proceeding to handler for %s.",
            user.id,
            user.username,
            type(event).__name__,
        )
        return await handler(event, data)
