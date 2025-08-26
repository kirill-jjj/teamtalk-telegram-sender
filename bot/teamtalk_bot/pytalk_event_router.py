"""Route Pytalk (TeamTalk) events to the correct TeamTalkConnection."""

from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import Any

from dishka import AsyncContainer
import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser

from bot.event_bus.bus import EventBus
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.enums import PytalkEvent
from bot.teamtalk_bot.events import UserJoinedEvent, UserLeftEvent
from bot.teamtalk_bot.formatters import get_effective_server_name
from bot.teamtalk_bot.message_handler import MessageHandler

logger = logging.getLogger(__name__)


# Decorator definition
def route_event_to_connection(
    handler_method_on_event_handler_class: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Decorator for PytalkEventRouter methods to route events.

    Routes to the appropriate TeamTalkConnection instance.
    It assumes the decorated method's first arg after 'self' is the primary
    Pytalk event object.
    """

    @functools.wraps(handler_method_on_event_handler_class)
    async def wrapper(
        self_event_handler: "PytalkEventRouter",
        event_primary_obj: Any,  # Intentionally Any for generic event object
        *args: Any,
        **kwargs: Any,
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
            # Instead of calling the method on the connection, we call the handler
            # on ourself (the router) and pass the connection as an argument.
            await handler_method_on_event_handler_class(
                self_event_handler,
                event_primary_obj,
                *args,
                connection=connection,
                **kwargs,
            )
        else:
            logger.warning(
                "Decorator: No active TTConnection for instance %s in Pytalk evt '%s'.",
                tt_instance,
                handler_name_for_logs,
            )

    return wrapper


async def _broadcast_event_to_all_connections(
    self_event_handler: "PytalkEventRouter",
    event_primary_obj: Any,
    method_name_on_connection: str,
    handler_name_for_logs: str,
    *args: Any,
    **kwargs: Any,
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


class PytalkEventRouter:
    """Routes Pytalk events to the corresponding TeamTalkConnection instance."""

    def __init__(
        self,
        app_container: AsyncContainer,
        tt_bot: pytalk.TeamTalkBot,
        connections: dict[str, TeamTalkConnection],
        event_bus: EventBus,
        translator_factory: Callable[[str], NullTranslations],
    ) -> None:
        """Initializes the PytalkEventRouter."""
        self.app_container = app_container
        self.tt_bot = tt_bot
        self.connections = connections
        self.event_bus = event_bus
        self.translator_factory = translator_factory
        self.logger = logging.getLogger(__name__)
        self._register_pytalk_event_handlers()
        self.logger.info(
            "PytalkEventRouter initialized and Pytalk event handlers registered."
        )

    def _register_pytalk_event_handlers(self) -> None:
        """Registers Pytalk event handlers with the PytalkBot instance."""
        event_handlers_map = {
            # on_ready is no longer needed here, it's handled by the provider
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

    async def _publish_user_event(
        self,
        user: PytalkUser,
        connection: TeamTalkConnection,
        event_class: type[UserJoinedEvent] | type[UserLeftEvent],
    ) -> None:
        """Generic helper to publish user-related domain events."""
        if not connection.instance:
            return

        # The router now has the translator factory and can get the settings
        # from the connection object to resolve the effective server name.
        translator = self.translator_factory(connection.settings.general.default_lang)
        server_name = get_effective_server_name(
            connection.instance, translator, connection.settings
        )

        event = event_class(
            user_nickname=connection.ttstr(user.nickname).strip(),
            username=connection.ttstr(user.username),
            user_id=user.id,
            server_name=server_name,
            online_users_cache=connection.cache_manager.online_users_cache,
        )
        await self.event_bus.publish(event)

    @route_event_to_connection
    async def on_pytalk_my_login(
        self, server: PytalkServer, connection: TeamTalkConnection
    ) -> None:
        """Handles the bot's own login event for a specific connection."""
        await connection.on_my_login(server)

    @route_event_to_connection
    async def on_pytalk_user_join(
        self, user: PytalkUser, channel: PytalkChannel, connection: TeamTalkConnection
    ) -> None:
        """Handles a user join event for a specific connection."""
        await connection.on_user_join(user, channel)

    @route_event_to_connection
    async def on_pytalk_my_connection_lost(
        self, server: PytalkServer, connection: TeamTalkConnection
    ) -> None:
        """Handles a connection lost event for the bot for a specific connection."""
        await connection.on_my_connection_lost(server)

    @route_event_to_connection
    async def on_pytalk_my_kicked_from_channel(
        self, channel_obj: PytalkChannel, connection: TeamTalkConnection
    ) -> None:
        """Handles a kicked from channel event for the bot for a specific connection."""
        await connection.on_my_kicked_from_channel(channel_obj)

    @route_event_to_connection
    async def on_pytalk_message(
        self, message: TeamTalkMessage, connection: TeamTalkConnection
    ) -> None:
        """Handles an incoming message event for a specific connection."""
        # Create a request scope for each message
        async with self.app_container(
            context={TeamTalkMessage: message, TeamTalkConnection: connection}
        ) as request_container:
            message_handler = await request_container.get(MessageHandler)
            await message_handler.route_message(message)

    @route_event_to_connection
    async def on_pytalk_user_login(
        self, user: PytalkUser, connection: TeamTalkConnection
    ) -> None:
        """Handles user login, updates cache, and publishes a domain event."""
        connection.cache_manager.update_caches_on_event(PytalkEvent.USER_LOGIN, user)
        await self._publish_user_event(user, connection, UserJoinedEvent)

    @route_event_to_connection
    async def on_pytalk_user_logout(
        self, user: PytalkUser, connection: TeamTalkConnection
    ) -> None:
        """Handles user logout, updates cache, and publishes a domain event."""
        connection.cache_manager.update_caches_on_event(PytalkEvent.USER_LOGOUT, user)
        await self._publish_user_event(user, connection, UserLeftEvent)

    @route_event_to_connection
    async def on_pytalk_user_update(
        self, user: PytalkUser, connection: TeamTalkConnection
    ) -> None:
        """Handles a user update event for a specific connection."""
        await connection.on_user_update(user)

    @route_event_to_connection
    async def on_pytalk_user_account_new(
        self, account: pytalk.UserAccount, connection: TeamTalkConnection
    ) -> None:
        """Handles a new user account event for a specific connection."""
        await connection.on_user_account_new(account)

    @route_event_to_connection
    async def on_pytalk_user_account_remove(
        self, account: pytalk.UserAccount, connection: TeamTalkConnection
    ) -> None:
        """Handles a removed user account event for a specific connection."""
        await connection.on_user_account_remove(account)
