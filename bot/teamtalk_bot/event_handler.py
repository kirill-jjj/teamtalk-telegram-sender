"""Handles events received from the Pytalk (TeamTalk) library by routing them to the appropriate TeamTalkConnection."""

from collections.abc import Awaitable, Callable
import functools
import logging
from typing import TYPE_CHECKING, Any

import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser

from bot.constants import INVALID_CHANNEL_ID
from bot.teamtalk_bot.connection import TeamTalkConnection

if TYPE_CHECKING:
    from bot.services_container import Services


logger = logging.getLogger(__name__)


# Decorator definition
def route_event_to_connection(
    handler_method_on_event_handler_class: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Decorator for TeamTalkEventHandler methods to route events.

    Routes to the appropriate TeamTalkConnection instance.
    It assumes the decorated method's first arg after 'self' is the primary Pytalk event object.
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

        # Special handling for on_my_connection_lost (SIM102 fix incorporated)
        if (
            not tt_instance
            and handler_method_on_event_handler_class.__name__ == "on_pytalk_my_connection_lost"
            and isinstance(event_primary_obj, PytalkServer)
            and event_primary_obj.info
        ):
            connection = self_event_handler._get_connection_by_server_info(event_primary_obj.info)
            if connection:
                await connection.on_my_connection_lost(event_primary_obj, *args, **kwargs)
            else:
                logger.error(
                    "Decorator: ConnectionLost: No connection by server_info for %s",
                    f"{event_primary_obj.info.host}:{event_primary_obj.info.tcp_port}",
                )
            return

        if not tt_instance:
            logger.error(
                "Decorator: Could not determine TeamTalk instance for event_obj type '%s' in handler '%s'.",
                type(event_primary_obj).__name__,
                handler_method_on_event_handler_class.__name__,
            )
            return

        connection = self_event_handler._get_connection_by_instance(tt_instance)
        if connection:
            method_name_on_connection = handler_method_on_event_handler_class.__name__.replace("on_pytalk_", "on_")
            actual_connection_method = getattr(connection, method_name_on_connection, None)

            if actual_connection_method and callable(actual_connection_method):
                await actual_connection_method(event_primary_obj, *args, **kwargs)
            else:
                logger.error(
                    "Decorator: Method '%s' not found or not callable on TeamTalkConnection for Pytalk event '%s'.",
                    method_name_on_connection,
                    handler_method_on_event_handler_class.__name__,
                )
        else:
            logger.warning(
                "Decorator: No active TeamTalkConnection found for instance %s in Pytalk event '%s'.",
                tt_instance,
                handler_method_on_event_handler_class.__name__,
            )

    return wrapper


class TeamTalkEventHandler:
    """Routes Pytalk events to the corresponding TeamTalkConnection instance."""

    def __init__(self, services: "Services") -> None:
        """Initializes the TeamTalkEventHandler."""
        self.services = services
        self.tt_bot = services.tt_bot
        self._register_pytalk_event_handlers()
        self.services.logger.info("TeamTalkEventHandler initialized and Pytalk event handlers registered.")

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

    def _get_connection_by_instance(self, tt_instance: pytalk.instance.TeamTalkInstance) -> TeamTalkConnection | None:
        """Retrieves an active TeamTalkConnection associated with the given Pytalk instance."""
        for conn in self.services.connections.values():
            if conn.instance is tt_instance:
                return conn
        self.services.logger.warning("Could not find active TeamTalkConnection for instance: %s", tt_instance)
        return None

    def _get_connection_by_server_info(self, server_info: pytalk.TeamTalkServerInfo) -> TeamTalkConnection | None:
        """Retrieves an active TeamTalkConnection by server host and port."""
        server_key = f"{server_info.host}:{server_info.tcp_port}"
        return self.services.connections.get(server_key)

    async def on_pytalk_ready(self) -> None:
        """Handles PytalkBot on_ready; initializes primary TeamTalk server connection."""
        self.services.logger.info("Pytalk Bot ready. Initializing TT connections...")
        tt_config = self.services.config.teamtalk

        pytalk_server_info = pytalk.TeamTalkServerInfo(
            host=tt_config.host_name,
            tcp_port=tt_config.port,
            udp_port=tt_config.port,
            username=tt_config.user_name,
            password=tt_config.password,
            encrypted=tt_config.encrypted,
            nickname=tt_config.nick_name,
            join_channel_id=int(tt_config.channel) if tt_config.channel.isdigit() else INVALID_CHANNEL_ID,
            join_channel_password=tt_config.channel_password or "",
        )
        server_key = f"{pytalk_server_info.host}:{pytalk_server_info.tcp_port}"

        if server_key in self.services.connections:
            logger.warning("Connection for %s exists. Reconnecting.", server_key)
            connection = self.services.connections[server_key]
            await connection.disconnect_instance()
        else:
            connection = TeamTalkConnection(pytalk_server_info, self.tt_bot, self.services)
            self.services.connections[server_key] = connection

        logger.info("Connecting TeamTalkConnection for %s...", server_key)
        if not await connection.connect():
            logger.error("Failed to init connection for %s.", server_key)
        else:
            logger.info("TeamTalkConnection for %s initiated.", server_key)

    @route_event_to_connection
    async def on_pytalk_my_login(self, server: PytalkServer) -> None:
        """Routes the bot's own login event to the appropriate connection via decorator."""
        # Logic moved to decorator and TeamTalkConnection.on_my_login

    @route_event_to_connection
    async def on_pytalk_user_join(self, user: PytalkUser, channel: PytalkChannel) -> None:
        """Routes a user join event to the appropriate connection via decorator."""
        # Logic moved to decorator and TeamTalkConnection.on_user_join

    @route_event_to_connection
    async def on_pytalk_my_connection_lost(self, server: PytalkServer) -> None:
        """Routes a connection lost event for the bot to the appropriate connection via decorator."""
        # Logic moved to decorator and TeamTalkConnection.on_my_connection_lost

    @route_event_to_connection
    async def on_pytalk_my_kicked_from_channel(self, channel_obj: PytalkChannel) -> None:
        """Routes a kicked from channel event for the bot to the appropriate connection via decorator."""
        # Logic moved to decorator and TeamTalkConnection.on_my_kicked_from_channel

    @route_event_to_connection
    async def on_pytalk_message(self, message: TeamTalkMessage) -> None:
        """Routes an incoming message event to the appropriate connection via decorator."""
        # Logic moved to decorator and TeamTalkConnection.on_message

    @route_event_to_connection
    async def on_pytalk_user_login(self, user: PytalkUser) -> None:
        """Routes a user login event to the appropriate connection via decorator."""
        # Logic moved to decorator and TeamTalkConnection.on_user_login

    @route_event_to_connection
    async def on_pytalk_user_logout(self, user: PytalkUser) -> None:
        """Routes a user logout event to the appropriate connection via decorator."""
        # Logic moved to decorator and TeamTalkConnection.on_user_logout

    @route_event_to_connection
    async def on_pytalk_user_update(self, user: PytalkUser) -> None:
        """Routes a user update event to the appropriate connection via decorator."""
        # Logic moved to decorator and TeamTalkConnection.on_user_update

    async def on_pytalk_user_account_new(self, account: pytalk.UserAccount) -> None:
        """Routes a new user account event, potentially to all connections."""
        tt_instance = getattr(account, "teamtalk_instance", None)
        if tt_instance:
            connection = self._get_connection_by_instance(tt_instance)
            if connection:
                await connection.on_user_account_new(account)
            else:
                logger.error("AccountNew: No connection for instance %s", tt_instance)
        else:
            logger.warning("AccountNew: No instance on account. Broadcasting.")
            for _conn_key, conn_val in self.services.connections.items():  # Use items()
                await conn_val.on_user_account_new(account)

    async def on_pytalk_user_account_remove(self, account: pytalk.UserAccount) -> None:
        """Routes a removed user account event, potentially to all connections."""
        tt_instance = getattr(account, "teamtalk_instance", None)
        if tt_instance:
            connection = self._get_connection_by_instance(tt_instance)
            if connection:
                await connection.on_user_account_remove(account)
            else:
                logger.error("AccountRemove: No connection for instance %s", tt_instance)
        else:
            logger.warning("AccountRemove: No instance on account. Broadcasting.")
            for _conn_key, conn_val in self.services.connections.items():  # Use items()
                await conn_val.on_user_account_remove(account)
