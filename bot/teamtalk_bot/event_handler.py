"""Route Pytalk (TeamTalk) events to the correct TeamTalkConnection."""

from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import Any

import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser

from bot.config import Settings
from bot.constants import INVALID_CHANNEL_ID
from bot.database.engine import AsyncSessionFactoryType
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.types.bots import EventBot, MessageBot

logger = logging.getLogger(__name__)


# Decorator definition
def route_event_to_connection(
    handler_method_on_event_handler_class: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Decorator for TeamTalkEventHandler methods to route events.

    Routes to the appropriate TeamTalkConnection instance.
    It assumes the decorated method's first arg after 'self' is the primary
    Pytalk event object.
    """

    @functools.wraps(handler_method_on_event_handler_class)
    async def wrapper(
        self_event_handler: "TeamTalkEventHandler",
        event_primary_obj: Any,  # noqa: ANN401 # Intentionally Any for generic event object
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        """Wrapper function for the decorator to handle event routing."""
        tt_instance = None
        # 1. Direct attribute from primary event object
        tt_instance = getattr(event_primary_obj, "teamtalk_instance", None)

        # 2. Via .server attribute (common for User if instance is on Server)
        if not tt_instance and hasattr(event_primary_obj, "server"):
            server_obj = event_primary_obj.server
            if server_obj:
                tt_instance = getattr(server_obj, "teamtalk_instance", None)

        # 3. Via .teamtalk attribute (common for Channel)
        if not tt_instance and hasattr(event_primary_obj, "teamtalk"):
            tt_instance = getattr(event_primary_obj, "teamtalk", None)

        # Special handling for on_my_connection_lost
        if (
            not tt_instance
            and handler_method_on_event_handler_class.__name__
            == "on_pytalk_my_connection_lost"
            and isinstance(event_primary_obj, PytalkServer)
            and event_primary_obj.info
        ):
            connection = self_event_handler._get_connection_by_server_info(
                event_primary_obj.info
            )
            if connection:
                await connection.on_my_connection_lost(
                    event_primary_obj, *args, **kwargs
                )
            else:
                logger.error(
                    "Decorator: ConnectionLost: No connection by server_info for %s",
                    f"{event_primary_obj.info.host}:{event_primary_obj.info.tcp_port}",
                )
            return

        method_name_on_connection = (
            handler_method_on_event_handler_class.__name__.replace("on_pytalk_", "on_")
        )
        handler_name_for_logs = handler_method_on_event_handler_class.__name__

        if not tt_instance:
            if handler_name_for_logs in (
                "on_pytalk_user_account_new",
                "on_pytalk_user_account_remove",
            ):
                await _broadcast_event_to_all_connections(
                    self_event_handler,
                    event_primary_obj,
                    method_name_on_connection,
                    handler_name_for_logs,
                    *args,
                    **kwargs,
                )
                return
            logger.error(
                "Decorator: No TT instance for evt type '%s' in '%s'. Not routed.",
                type(event_primary_obj).__name__,
                handler_name_for_logs,
            )
            return

        connection = self_event_handler._get_connection_by_instance(tt_instance)
        if connection:
            actual_connection_method = getattr(
                connection, method_name_on_connection, None
            )
            if actual_connection_method and callable(actual_connection_method):
                await actual_connection_method(event_primary_obj, *args, **kwargs)
            else:
                logger.error(
                    "Decorator: Method '%s' not found/callable on TTConnection "
                    "for Pytalk evt '%s'.",
                    method_name_on_connection,
                    handler_name_for_logs,
                )
        else:
            logger.warning(
                "Decorator: No active TTConnection for instance %s in Pytalk evt '%s'.",
                tt_instance,
                handler_name_for_logs,
            )

    return wrapper


async def _broadcast_event_to_all_connections(
    self_event_handler: "TeamTalkEventHandler",
    event_primary_obj: Any,  # noqa: ANN401
    method_name_on_connection: str,
    handler_name_for_logs: str,
    *args: Any,  # noqa: ANN401
    **kwargs: Any,  # noqa: ANN401
) -> None:
    """Helper to broadcast an event to all active TeamTalkConnection instances."""
    logger.info(
        "Broadcasting: Evt '%s' (type: %s) to all conns (no specific instance).",
        handler_name_for_logs,
        type(event_primary_obj).__name__,
    )
    broadcast_count = 0
    if not hasattr(self_event_handler, "connections"):
        logger.error(
            "Broadcast: connections unavailable for '%s'.", handler_name_for_logs
        )
        return

    for conn_key, connection_obj in self_event_handler.connections.items():
        if not isinstance(connection_obj, TeamTalkConnection):
            logger.error(
                "Broadcast: Invalid obj for key '%s' (event: '%s'). Skip.",
                conn_key,
                handler_name_for_logs,
            )
            continue
        actual_connection_method = getattr(
            connection_obj, method_name_on_connection, None
        )
        if actual_connection_method and callable(actual_connection_method):
            try:
                await actual_connection_method(event_primary_obj, *args, **kwargs)
                broadcast_count += 1
            except Exception:
                logger.exception(
                    "Broadcast: Error during call of method '%s' to conn "
                    "for key '%s' for evt '%s'.",
                    method_name_on_connection,
                    conn_key,
                    handler_name_for_logs,
                )
        else:
            logger.error(
                "Broadcast: Method '%s' not on TTConn for key '%s', evt '%s'.",
                method_name_on_connection,
                conn_key,
                handler_name_for_logs,
            )
    if broadcast_count > 0:
        logger.info(
            "Broadcast: Event '%s' sent to %d connections.",
            handler_name_for_logs,
            broadcast_count,
        )
    else:
        logger.warning(
            "Broadcast: Evt '%s' for broadcast, not sent to any conns.",
            handler_name_for_logs,
        )


class TeamTalkEventHandler:
    """Routes Pytalk events to the corresponding TeamTalkConnection instance."""

    def __init__(
        self,
        settings: Settings,
        session_factory: AsyncSessionFactoryType,
        cache: CacheService,
        translator_factory: Callable[[str], NullTranslations],
        event_bot: EventBot,
        message_bot: MessageBot,
        tt_bot: pytalk.TeamTalkBot,
        connections: dict[str, TeamTalkConnection],
        logger: logging.Logger,
    ) -> None:
        """Initializes the TeamTalkEventHandler."""
        self.settings = settings
        self.session_factory = session_factory
        self.cache = cache
        self.translator_factory = translator_factory
        self.event_bot = event_bot
        self.message_bot = message_bot
        self.tt_bot = tt_bot
        self.connections = connections
        self.logger = logger
        self._register_pytalk_event_handlers()
        self.logger.info(
            "TeamTalkEventHandler initialized and Pytalk event handlers registered."
        )

    def _register_pytalk_event_handlers(self) -> None:
        """Registers Pytalk event handlers with the PytalkBot instance."""
        event_handlers_map = {
            "on_ready": self.on_pytalk_ready,
            "on_my_login": self.on_pytalk_my_login,
            "on_my_connection_lost": self.on_pytalk_my_connection_lost,
            "on_my_kicked_from_channel": self.on_pytalk_my_kicked_from_channel,
            "on_message": self.on_pytalk_message,
            "on_user_login": self.on_pytalk_user_login,
            "on_user_join": self.on_pytalk_user_join,
            "on_user_logout": self.on_pytalk_user_logout,
            "on_user_update": self.on_pytalk_user_update,
            "on_user_account_new": self.on_pytalk_user_account_new,
            "on_user_account_remove": self.on_pytalk_user_account_remove,
        }
        for event_name, handler_method in event_handlers_map.items():
            setattr(self.tt_bot, event_name, self.tt_bot.event(handler_method))

    def _get_connection_by_instance(
        self, tt_instance: pytalk.instance.TeamTalkInstance
    ) -> TeamTalkConnection | None:
        """Get an active TeamTalkConnection for the given Pytalk instance."""
        for conn in self.connections.values():
            if conn.instance is tt_instance:
                return conn
        self.logger.warning(
            "Could not find active TeamTalkConnection for instance: %s", tt_instance
        )
        return None

    def _get_connection_by_server_info(
        self, server_info: pytalk.TeamTalkServerInfo
    ) -> TeamTalkConnection | None:
        """Retrieves an active TeamTalkConnection by server host and port."""
        server_key = f"{server_info.host}:{server_info.tcp_port}"
        return self.connections.get(server_key)

    async def on_pytalk_ready(self) -> None:
        """Handle PytalkBot on_ready; init primary TeamTalk server connection."""
        self.logger.info("Pytalk Bot ready. Initializing TT connections...")
        tt_config = self.settings.teamtalk

        pytalk_server_info = pytalk.TeamTalkServerInfo(
            host=tt_config.host_name,
            tcp_port=tt_config.port,
            udp_port=tt_config.port,
            username=tt_config.user_name,
            password=tt_config.password,
            encrypted=tt_config.encrypted,
            nickname=self.settings.teamtalk.nick_name,
            join_channel_id=int(tt_config.channel)
            if tt_config.channel.isdigit()
            else INVALID_CHANNEL_ID,
            join_channel_password=tt_config.channel_password or "",
        )
        server_key = f"{pytalk_server_info.host}:{pytalk_server_info.tcp_port}"

        if server_key in self.connections:
            logger.warning("Connection for %s exists. Reconnecting.", server_key)
            connection = self.connections[server_key]
            await connection.disconnect_instance()
        else:
            connection = TeamTalkConnection(
                pytalk_server_info,
                self.tt_bot,
                self.settings,
                self.session_factory,
                self.cache,
                self.translator_factory,
                self.event_bot,
                self.message_bot,
            )
            self.connections[server_key] = connection

        logger.info("Connecting TeamTalkConnection for %s...", server_key)
        if not await connection.connect():
            logger.error("Failed to init connection for %s.", server_key)
        else:
            logger.info("TeamTalkConnection for %s initiated.", server_key)

    @route_event_to_connection
    async def on_pytalk_my_login(self, server: PytalkServer) -> None:
        """Route the bot's own login event to the correct connection via decorator."""

    @route_event_to_connection
    async def on_pytalk_user_join(
        self, user: PytalkUser, channel: PytalkChannel
    ) -> None:
        """Routes a user join event to the appropriate connection via decorator."""

    @route_event_to_connection
    async def on_pytalk_my_connection_lost(self, server: PytalkServer) -> None:
        """Route a connection lost event for the bot to the correct connection."""

    @route_event_to_connection
    async def on_pytalk_my_kicked_from_channel(
        self, channel_obj: PytalkChannel
    ) -> None:
        """Route a kicked from channel event for the bot to the correct connection."""

    @route_event_to_connection
    async def on_pytalk_message(self, message: TeamTalkMessage) -> None:
        """Route an incoming message event to the correct connection via decorator."""

    @route_event_to_connection
    async def on_pytalk_user_login(self, user: PytalkUser) -> None:
        """Routes a user login event to the appropriate connection via decorator."""

    @route_event_to_connection
    async def on_pytalk_user_logout(self, user: PytalkUser) -> None:
        """Routes a user logout event to the appropriate connection via decorator."""

    @route_event_to_connection
    async def on_pytalk_user_update(self, user: PytalkUser) -> None:
        """Routes a user update event to the appropriate connection via decorator."""

    @route_event_to_connection
    async def on_pytalk_user_account_new(self, account: pytalk.UserAccount) -> None:
        """Route a new user account event. Instance/broadcast handled by decorator."""

    @route_event_to_connection
    async def on_pytalk_user_account_remove(self, account: pytalk.UserAccount) -> None:
        """Route a removed user account event. Instance/broadcast handled by decorator."""
