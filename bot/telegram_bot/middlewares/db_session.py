"""Middleware to provide a database session to Telegram handlers."""

from collections.abc import Callable, Coroutine
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.orm import sessionmaker


class DbSessionMiddleware(BaseMiddleware):
    """Middleware to provide a database session to handlers."""

    def __init__(self, session_factory: sessionmaker):  # type: ignore
        """Initializes DbSessionMiddleware.

        Args:
            session_factory: The SQLAlchemy session factory.
        """
        super().__init__()
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
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
