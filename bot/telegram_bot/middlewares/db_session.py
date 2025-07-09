"""Middleware to provide a database session to Telegram handlers."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.database.engine import AsyncSessionFactoryType  # Import the specific session factory type


class DbSessionMiddleware(BaseMiddleware):
    """Middleware to provide a database session to handlers."""

    def __init__(self, session_factory: AsyncSessionFactoryType) -> None:  # type: ignore[type-var]
        """Initializes DbSessionMiddleware.

        Args:
            session_factory: The SQLModel/SQLAlchemy session factory.
        """
        super().__init__()
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:  # noqa: ANN401
        """Executes the middleware.

        Creates a new database session and injects it into the data dictionary
        for subsequent handlers.

        Args:
            handler: The next handler in the chain.
            event: The incoming Telegram event.
            data: Data to be passed to the handler.

        Returns:
            The result of the next handler.
        """
        async with self.session_factory() as session:
            data["session"] = session
            return await handler(event, data)
