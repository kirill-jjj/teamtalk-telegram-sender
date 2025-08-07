"""Custom filter to check if a user is a subscribed."""

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka

from bot.services.cache_service import CacheService


class IsSubscribed(Filter):
    """Checks if the user is in the cache of subscribed users."""

    async def __call__(
        self,
        event: Message | CallbackQuery,
        cache: FromDishka[CacheService],
    ) -> bool:
        """Filter logic."""
        if not event.from_user:
            return False

        # Allow /start commands with a deeplink payload to pass through
        # for new user registration.
        if (
            isinstance(event, Message)
            and event.text
            and event.text.startswith("/start ")
        ):
            return True

        return cache.is_subscribed(event.from_user.id)
