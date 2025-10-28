"""Admin filter for Aiogram handlers."""

from typing import TYPE_CHECKING, Any

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from bot.services.cache_service import CacheService

if TYPE_CHECKING:
    from dishka import AsyncContainer


class IsAdmin(Filter):
    """Filter to check if a user is a bot administrator."""

    async def __call__(
        self,
        event: Message | CallbackQuery,
        **data: Any,  # noqa: ANN401
    ) -> bool:
        """Check if the user ID from the event is in the admin cache.

        This method manually retrieves the dishka container from the event data
        because dependency injection does not work directly in Aiogram filters.

        Args:
            event: The message or callback query that triggered the handler.
            data: A dictionary of extra data passed by middlewares,
                  which includes the dishka_container.

        Returns:
            True if the user is an admin, False otherwise.
        """
        if not event.from_user:
            return False

        # 1. Get the container from the data passed down the chain
        container: AsyncContainer = data["dishka_container"]
        if not container:
            return False

        # 2. Get the required service from the container manually
        cache: CacheService = await container.get(CacheService)

        # 3. Perform the check
        return cache.is_admin(event.from_user.id)
