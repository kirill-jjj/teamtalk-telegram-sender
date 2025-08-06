"""Custom filter to check for administrator privileges."""

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka

from bot.services.cache_service import CacheService


class IsAdmin(Filter):
    """Filter to check if a user is a bot administrator."""

    async def __call__(self, event: Message | CallbackQuery, cache: FromDishka[CacheService]) -> bool:
        """Check if the user ID from the event is in the admin cache.

        Args:
            event: The message or callback query that triggered the handler.
            cache: The cache service, injected by dishka.

        Returns:
            True if the user is an admin, False otherwise.
        """
        if not event.from_user:
            return False
        return cache.is_admin(event.from_user.id)
