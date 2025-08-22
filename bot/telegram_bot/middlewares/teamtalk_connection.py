"""Middlewares for managing and checking TeamTalk connections for Telegram handlers."""

from collections.abc import (
    Awaitable,
    Callable,
)
import logging
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)


class ActiveTeamTalkConnectionMiddleware(BaseMiddleware):
    """Injects an active TeamTalkConnection instance into the event data."""

    def __init__(self, default_server_key: str | None = None) -> None:
        """Initializes ActiveTeamTalkConnectionMiddleware."""
        super().__init__()
        self.default_server_key = default_server_key

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Executes the middleware."""
        container = data["dishka_container"]
        connections: dict[str, TeamTalkConnection] = await container.get(
            dict[str, TeamTalkConnection]
        )
        determined_connection: TeamTalkConnection | None = None

        if not connections:
            logger.warning(
                "ActiveTeamTalkConnectionMiddleware: No TeamTalk connections found."
            )
            data["tt_connection"] = None
            return await handler(event, data)

        if self.default_server_key and self.default_server_key in connections:
            determined_connection = connections[self.default_server_key]
        elif connections:
            determined_connection = next(iter(connections.values()), None)
            if self.default_server_key and not determined_connection:
                logger.warning(
                    "ActiveTeamTalkConnectionMiddleware: Default server key '%s' "
                    "not found. Falling back to first available connection if any.",
                    self.default_server_key,
                )
            elif determined_connection:
                logger.debug(
                    "ActiveTeamTalkConnectionMiddleware: Using first available "
                    "connection for %s.",
                    determined_connection.server_info.host,
                )

        if determined_connection:
            logger.debug(
                "ActiveTeamTalkConnectionMiddleware: Providing connection for "
                "%s to handler.",
                determined_connection.server_info.host,
            )
        else:
            logger.warning(
                "ActiveTeamTalkConnectionMiddleware: Could not determine a TeamTalk "
                "connection to provide."
            )

        data["tt_connection"] = determined_connection
        return await handler(event, data)
