from collections.abc import Callable, Coroutine
import gettext  # For translator type hint
import logging
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.teamtalk_bot.connection import TeamTalkConnection  # Assuming this is the correct path

from .utils import _send_error_response

if TYPE_CHECKING:
    # from sender import Application # No longer needed
    from bot.services_container import Services  # Import Services

logger = logging.getLogger(__name__)


class ActiveTeamTalkConnectionMiddleware(BaseMiddleware):
    """Injects an active TeamTalkConnection instance into the event data.
    For now, assumes a single primary connection if multiple exist.
    Relies on 'connections' (Dict[str, TeamTalkConnection]) being in workflow_data.
    """

    def __init__(self, default_server_key: str | None = None):
        super().__init__()
        self.default_server_key = default_server_key

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # services: "Services" = data["services"] # Get services from workflow_data
        # More direct to get connections if it's already in workflow_data
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
                    f"ActiveTeamTalkConnectionMiddleware: Default server key '{self.default_server_key}' "
                    f"not found. Falling back to first available connection if any."
                )
            elif determined_connection:
                logger.debug(
                    f"ActiveTeamTalkConnectionMiddleware: Using first available connection "
                    f"for {determined_connection.server_info.host}."
                )
            # else: no connections available, determined_connection remains None

        if determined_connection:
            logger.debug(
                f"ActiveTeamTalkConnectionMiddleware: Providing connection for "
                f"{determined_connection.server_info.host} to handler."
            )
        else:
            logger.warning("ActiveTeamTalkConnectionMiddleware: Could not determine a TeamTalk connection to provide.")

        data["tt_connection"] = determined_connection
        return await handler(event, data)


class TeamTalkConnectionCheckMiddleware(BaseMiddleware):
    """Checks if the provided TeamTalkConnection (from ActiveTeamTalkConnectionMiddleware)
    is connected and logged in (ready for use).
    If not, it replies to the user and prevents the handler from executing.
    Relies on 'tt_connection' and 'translator' (or 'services') being in workflow_data.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tt_connection: TeamTalkConnection | None = data.get("tt_connection")
        translator: gettext.GNUTranslations | None = data.get("translator")

        # Fallback to get translator from services if not directly available
        if not translator:
            services: Services | None = data.get("services")
            if services:
                # Assuming UserSettingsMiddleware ran and set a language-specific translator
                # If not, this will get the default one based on user_settings or config.
                # This part depends on UserSettingsMiddleware having run or a default being available.
                # For simplicity, we assume `data['translator']` is usually populated by UserSettingsMiddleware.
                # If UserSettingsMiddleware hasn't run (e.g. error before it), we might need a more robust fallback.
                # For now, let's assume user_settings is in data IF a user is involved.
                user_settings = data.get("user_settings")
                lang_code = user_settings.language_code if user_settings else None
                translator = services.get_translator(lang_code)
            else:  # Absolute fallback: create a temporary default translator
                logger.warning(
                    "TeamTalkConnectionCheckMiddleware: Translator and Services not found in data. "
                    "Using temporary default translator."
                )
                translator = gettext.NullTranslations()  # Should not happen in normal flow

        _ = translator.gettext

        if not tt_connection:
            error_message_text = _("TeamTalk service is currently unavailable. Please try again later.")
            await _send_error_response(event, error_message_text, show_alert_for_callback=True)
            user_id_info = data.get("event_from_user", {}).get("id", "Unknown User")
            logger.warning(
                f"TeamTalkConnectionCheckMiddleware: Blocked access for user {user_id_info} "
                f"because no TeamTalkConnection object was found in context. Event type: {type(event).__name__}"
            )
            return None  # Stop processing

        if not tt_connection.is_ready or not tt_connection.is_finalized:
            error_message_text = _("TeamTalk bot is not connected or not fully initialized. Please try again later.")
            await _send_error_response(event, error_message_text, show_alert_for_callback=True)
            user_id_info = data.get("event_from_user", {}).get("id", "Unknown User")
            logger.warning(
                f"TeamTalkConnectionCheckMiddleware: Blocked access for user {user_id_info} "
                f"for server {tt_connection.server_info.host} due to TeamTalk not being ready "
                f"(connected: {tt_connection.instance.connected if tt_connection.instance else 'N/A'}, "
                f"logged_in: {tt_connection.instance.logged_in if tt_connection.instance else 'N/A'}, "
                f"finalized: {tt_connection.is_finalized}). Event type: {type(event).__name__}"
            )
            return None  # Stop processing

        logger.debug(
            f"TeamTalkConnectionCheckMiddleware: Access granted for server "
            f"{tt_connection.server_info.host}. Connection is ready."
        )
        return await handler(event, data)
