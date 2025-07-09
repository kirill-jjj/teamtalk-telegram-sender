"""Middlewares for managing and checking TeamTalk connections for Telegram handlers."""

from collections.abc import (
    Awaitable,  # Added Awaitable
    Callable,  # Added Coroutine
)
from gettext import GNUTranslations, NullTranslations
import logging
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.teamtalk_bot.connection import TeamTalkConnection

from .utils import _send_error_response

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ActiveTeamTalkConnectionMiddleware(BaseMiddleware):
    """Injects an active TeamTalkConnection instance into the event data.

    For now, assumes a single primary connection if multiple exist.
    Relies on 'connections' (Dict[str, TeamTalkConnection]) being in workflow_data.
    """

    def __init__(self, default_server_key: str | None = None) -> None:
        """Initializes ActiveTeamTalkConnectionMiddleware.

        Args:
            default_server_key: Optional key of the default TeamTalk server connection
                                to provide if multiple connections exist.
        """
        super().__init__()
        self.default_server_key = default_server_key

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:  # noqa: ANN401
        """Executes the middleware.

        Injects an active TeamTalkConnection instance into the data dictionary.
        It uses `default_server_key` if provided, otherwise the first available connection.

        Args:
            handler: The next handler in the chain.
            event: The incoming Telegram event.
            data: Data to be passed to the handler.

        Returns:
            The result of the next handler.
        """
        connections: dict[str, TeamTalkConnection] = data.get("connections", {})
        determined_connection: TeamTalkConnection | None = None

        if not connections:
            logger.warning("ActiveTeamTalkConnectionMiddleware: No TeamTalk connections found in workflow_data.")
            data["tt_connection"] = None
            return await handler(event, data)

        if self.default_server_key and self.default_server_key in connections:
            determined_connection = connections[self.default_server_key]
        elif connections:  # Get the first one if no specific key or key not found
            determined_connection = next(iter(connections.values()), None)
            if self.default_server_key and not determined_connection:  # Log if key was given but not found
                logger.warning(
                    "ActiveTeamTalkConnectionMiddleware: Default server key '%s' not found. "
                    "Falling back to first available connection if any.",
                    self.default_server_key,
                )
            elif determined_connection:
                logger.debug(
                    "ActiveTeamTalkConnectionMiddleware: Using first available connection for %s.",
                    determined_connection.server_info.host,
                )
            # else: no connections available, determined_connection remains None

        if determined_connection:
            logger.debug(
                "ActiveTeamTalkConnectionMiddleware: Providing connection for %s to handler.",
                determined_connection.server_info.host,
            )
        else:
            logger.warning("ActiveTeamTalkConnectionMiddleware: Could not determine a TeamTalk connection to provide.")

        data["tt_connection"] = determined_connection
        return await handler(event, data)


class TeamTalkConnectionCheckMiddleware(BaseMiddleware):
    """Checks if the provided TeamTalkConnection is connected and logged in.

    (from ActiveTeamTalkConnectionMiddleware)
    If not, it replies to the user and prevents the handler from executing.
    Relies on 'tt_connection' and 'translator' (or 'services') being in workflow_data.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:  # noqa: ANN401
        """Executes the middleware.

        Checks if the TeamTalk connection (injected by ActiveTeamTalkConnectionMiddleware)
        is ready. If not, sends an error message to the user and stops processing.

        Args:
            handler: The next handler in the chain.
            event: The incoming Telegram event.
            data: Data to be passed to the handler.

        Returns:
            The result of the next handler if connection is ready, or None otherwise.
        """
        tt_connection: TeamTalkConnection | None = data.get("tt_connection")

        # Translator is now guaranteed to be in data by I18nMiddleware
        translator: GNUTranslations | NullTranslations = data["translator"]
        _ = translator.gettext

        if not tt_connection:
            error_message_text = _("TeamTalk service is currently unavailable. Please try again later.")
            await _send_error_response(event, error_message_text, show_alert_for_callback=True)
            user_id_info = data.get("event_from_user", {}).get("id", "Unknown User")
            logger.warning(
                "TeamTalkConnectionCheckMiddleware: Blocked access for user %s due to no "
                "TeamTalkConnection object in context. Event type: %s",
                user_id_info,
                type(event).__name__,
            )
            return None  # Stop processing

        if not tt_connection.is_ready or not tt_connection.is_finalized:
            error_message_text = _("TeamTalk bot is not connected or not fully initialized. Please try again later.")
            await _send_error_response(event, error_message_text, show_alert_for_callback=True)
            user_id_info = data.get("event_from_user", {}).get("id", "Unknown User")
            logger.warning(
                "TeamTalkConnectionCheckMiddleware: Blocked access for user %s for server %s "
                "due to TeamTalk not being ready (connected: %s, logged_in: %s, finalized: %s). Event type: %s",
                user_id_info,
                tt_connection.server_info.host,
                tt_connection.instance.connected if tt_connection.instance else "N/A",
                tt_connection.instance.logged_in if tt_connection.instance else "N/A",
                tt_connection.is_finalized,
                type(event).__name__,
            )
            return None  # Stop processing

        logger.debug(
            "TeamTalkConnectionCheckMiddleware: Access granted for server %s. Connection is ready.",
            tt_connection.server_info.host,
        )
        return await handler(event, data)
