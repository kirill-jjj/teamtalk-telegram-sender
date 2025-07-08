"""Middleware to check if a Telegram user is subscribed to bot notifications."""

from collections.abc import Awaitable, Callable
import logging
from typing import TYPE_CHECKING, Any  # Added Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject  # Import TelegramObject
from aiogram.types import User as AiogramUser

if TYPE_CHECKING:
    pass  # Import Services for type hinting

logger = logging.getLogger(__name__)


class SubscriptionCheckMiddleware(BaseMiddleware):
    """Middleware to check if a user is subscribed before allowing access to certain handlers."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Executes the middleware.

        Checks if the user is subscribed. If not, and the command is not a /start command
        with a token, it stops processing. Otherwise, allows subscribed users or
        specific /start commands to proceed.

        Args:
            handler: The next handler in the chain.
            event: The incoming Telegram event (Message or CallbackQuery).
            data: Data to be passed to the handler.

        Returns:
            The result of the next handler if authorized, or None if not.
        """
        user: AiogramUser | None = data.get("event_from_user")
        services = data.get("services")

        if not services:
            logger.critical("SubscriptionCheckMiddleware: 'services' not found in data. Cannot perform subscription check.")
            # This situation should ideally not happen.
            # Depending on policy, might want to inform user or just block.
            return

        if not user:
            logger.warning("SubscriptionCheckMiddleware: No user found in event data.")
            return await handler(event, data)

        telegram_id = user.id

        if isinstance(event, Message) and event.text:
            command_parts = event.text.split()
            if command_parts[0].lower() == "/start" and len(command_parts) > 1:
                # This allows /start <token> for deeplinking, which might be used for initial subscription
                logger.debug(
                    "SubscriptionCheckMiddleware: Allowing /start command with potential token for user %s.",
                    telegram_id,
                )
                return await handler(event, data)

        if not services.cache.is_subscribed(telegram_id):
            logger.info(
                "SubscriptionCheckMiddleware: Ignored event from non-subscribed user %s (Event type: %s).",
                telegram_id,
                type(event).__name__,
            )
            return  # Stop processing for non-subscribed users

        logger.debug(
            "SubscriptionCheckMiddleware: User %s is subscribed. Proceeding (Event type: %s).",
            telegram_id,
            type(event).__name__,
        )
        return await handler(event, data)
