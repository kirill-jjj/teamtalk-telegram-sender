"""Custom filter to check if a user is a subscribed."""

from typing import TYPE_CHECKING, Any

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from bot.services.cache_service import CacheService

if TYPE_CHECKING:
    from dishka import AsyncContainer


class IsSubscribed(Filter):
    """Checks if the user is in the cache of subscribed users."""

    async def __call__(
        self,
        event: Message | CallbackQuery,
        **data: Any,
    ) -> bool:
        """Filter logic."""
        if not event.from_user:
            return False

        container: AsyncContainer = data["dishka_container"]
        if not container:
            return False

        cache: CacheService = await container.get(CacheService)

        # Allow /start commands with a deeplink payload to pass through
        # for new user registration.
        if (
            isinstance(event, Message)
            and event.text
            and event.text.startswith("/start ")
        ):
            return True

        return cache.is_subscribed(event.from_user.id)
