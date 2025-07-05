import logging
from typing import Callable, Coroutine, Any, Dict, TYPE_CHECKING

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.teamtalk_bot.connection import TeamTalkConnection
from .utils import _send_error_response # Import from local utils

if TYPE_CHECKING:
    from sender import Application

logger = logging.getLogger(__name__)

class ActiveTeamTalkConnectionMiddleware(BaseMiddleware):
    """
    Injects an active TeamTalkConnection instance into the event data.
    For now, assumes a single primary connection if multiple exist.
    This replaces the old TeamTalkInstanceMiddleware.
    """
    def __init__(self, default_server_key: str | None = None):
        super().__init__()
        self.default_server_key = default_server_key # Optional: key for a default server if multiple

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        app: "Application" = data["app"]

        determined_connection: TeamTalkConnection | None = None

        if not app.connections:
            logger.warning("ActiveTeamTalkConnectionMiddleware: No TeamTalk connections available in Application.")
            data["tt_connection"] = None
            return await handler(event, data)

        if self.default_server_key and self.default_server_key in app.connections:
            determined_connection = app.connections[self.default_server_key]
        elif app.connections:
            determined_connection = next(iter(app.connections.values()))
            if self.default_server_key:
                 logger.warning(f"ActiveTeamTalkConnectionMiddleware: Default server key '{self.default_server_key}' not found. Falling back to first available connection.")
            else:
                 logger.debug(f"ActiveTeamTalkConnectionMiddleware: Using first available connection for {determined_connection.server_info.host if determined_connection else 'N/A'}.")

        if determined_connection:
            logger.debug(f"ActiveTeamTalkConnectionMiddleware: Providing connection for {determined_connection.server_info.host} to handler.")
        else:
            logger.warning("ActiveTeamTalkConnectionMiddleware: Could not determine a TeamTalk connection to provide.")

        data["tt_connection"] = determined_connection
        return await handler(event, data)


class TeamTalkConnectionCheckMiddleware(BaseMiddleware):
    """
    Checks if the provided TeamTalkConnection (from ActiveTeamTalkConnectionMiddleware)
    is connected and logged in (ready for use).
    If not, it replies to the user and prevents the handler from executing.
    This middleware should be registered for specific handlers/routers that require
    an active and ready TeamTalk connection.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tt_connection: TeamTalkConnection | None = data.get("tt_connection")
        app: "Application" = data["app"] # Ensure app is available
        translator = data.get("translator")

        if not translator:
            translator = app.get_translator()
        _ = translator.gettext

        if not tt_connection:
            error_message_text = _("TeamTalk service is currently unavailable. Please try again later.")
            await _send_error_response(event, error_message_text, show_alert_for_callback=True)
            logger.warning(
                f"TeamTalkConnectionCheckMiddleware: Blocked access for user {data.get('event_from_user', {}).get('id')} "
                f"because no TeamTalkConnection object was found in context. Event type: {type(event).__name__}"
            )
            return None

        if not tt_connection.is_ready or not tt_connection.is_finalized:
            error_message_text = _("TeamTalk bot is not connected or not fully initialized. Please try again later.")
            await _send_error_response(event, error_message_text, show_alert_for_callback=True)
            logger.warning(
                f"TeamTalkConnectionCheckMiddleware: Blocked access for user {data.get('event_from_user', {}).get('id')} "
                f"for server {tt_connection.server_info.host} due to TeamTalk not being ready "
                f"(connected: {tt_connection.instance.connected if tt_connection.instance else 'N/A'}, "
                f"logged_in: {tt_connection.instance.logged_in if tt_connection.instance else 'N/A'}, "
                f"finalized: {tt_connection.is_finalized}). Event type: {type(event).__name__}"
            )
            return None

        logger.debug(f"TeamTalkConnectionCheckMiddleware: Access granted for server {tt_connection.server_info.host}. Connection is ready.")
        return await handler(event, data)
