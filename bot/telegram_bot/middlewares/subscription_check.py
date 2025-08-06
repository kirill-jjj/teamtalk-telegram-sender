"""Middleware to check if a Telegram user is subscribed to bot notifications."""

from collections.abc import Awaitable, Callable
import logging
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from aiogram.types import User as AiogramUser

from bot.services.cache_service import CacheService

logger = logging.getLogger(__name__)


class SubscriptionCheckMiddleware(BaseMiddleware):
    """Middleware to check if a user is subscribed before allowing access to certain handlers."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Executes the middleware."""
        user: AiogramUser | None = data.get("event_from_user")
        cache: CacheService = data["cache"]

        if not user:
            logger.warning("SubscriptionCheckMiddleware: No user found in event data.")
            return await handler(event, data)

        telegram_id = user.id

        if isinstance(event, Message) and event.text:
            command_parts = event.text.split()
            if command_parts[0].lower() == "/start" and len(command_parts) > 1:
                logger.debug(
                    "SubscriptionCheckMiddleware: Allowing /start command with potential token for user %s.",
                    telegram_id,
                )
                return await handler(event, data)

        if not cache.is_subscribed(telegram_id):
            logger.info(
                "SubscriptionCheckMiddleware: Ignored event from non-subscribed user %s (Event type: %s).",
                telegram_id,
                type(event).__name__,
            )
            return None

        logger.debug(
            "SubscriptionCheckMiddleware: User %s is subscribed. Proceeding (Event type: %s).",
            telegram_id,
            type(event).__name__,
        )
        return await handler(event, data)
