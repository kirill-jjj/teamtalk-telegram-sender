"""Custom filter to check for administrator privileges."""

from typing import TYPE_CHECKING

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

if TYPE_CHECKING:
    from bot.services_container import Services


class IsAdmin(Filter):
    """Filter to check if a user is a bot administrator."""

    async def __call__(self, event: Message | CallbackQuery, services: "Services") -> bool:
        """Check if the user ID from the event is in the admin cache.

        Args:
            event: The message or callback query that triggered the handler.
            services: The services container, injected by a middleware.

        Returns:
            True if the user is an admin, False otherwise.
        """
        if not event.from_user:
            return False
        return services.cache.is_admin(event.from_user.id)
