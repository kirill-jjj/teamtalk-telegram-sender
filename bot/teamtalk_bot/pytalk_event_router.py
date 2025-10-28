"""Route Pytalk (TeamTalk) events to the correct TeamTalkConnection."""

from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging

from dishka import AsyncContainer
import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser

from bot.event_bus.bus import EventBus
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.handlers.pytalk_event_handlers import PytalkEventHandlers
from bot.teamtalk_bot.message_handler import MessageHandler

logger = logging.getLogger(__name__)


def route_event_to_connection(
    handler_method_on_router: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Decorator for PytalkEventRouter methods to route events."""

    @functools.wraps(handler_method_on_router)
    async def wrapper(
        self_event_router: "PytalkEventRouter",
        event_primary_obj: (
            PytalkServer
            | PytalkUser
            | PytalkChannel
            | TeamTalkMessage
            | pytalk.UserAccount
        ),
        *args: object,
        **kwargs: dict[str, object],
    ) -> None:
        """Wrapper function for the decorator to handle event routing."""
        tt_instance = _get_tt_instance_from_event(event_primary_obj)
        handler_name_for_logs = handler_method_on_router.__name__
        method_name_on_handler = handler_name_for_logs.replace("on_pytalk_", "on_")

        if not tt_instance:
            # Special case for connection loss where instance might not be on the event
            if (
                handler_name_for_logs == "on_pytalk_my_connection_lost"
                and isinstance(event_primary_obj, PytalkServer)
                and event_primary_obj.info
            ):
                connection = self_event_router._get_connection_by_server_info(
                    event_primary_obj.info
                )
                if connection:
                    await self_event_router.pytalk_event_handlers.on_my_connection_lost(
                        event_primary_obj, connection, *args, **kwargs
                    )
                else:
                    logger.error(
                        (
                            "Decorator: ConnectionLost: No connection by "
                            "server_info for %s",
                            f"{event_primary_obj.info.host}:{event_primary_obj.info.tcp_port}",
                        )
                    )
                return

            logger.error(
                "Decorator: No TT instance for evt type '%s' in '%s'. Not routed.",
                type(event_primary_obj).__name__,
                handler_name_for_logs,
            )
            return

        connection = self_event_router._get_connection_by_instance(tt_instance)
        if connection:
            # For on_pytalk_message, we need to call the handler on the router itself
            if handler_name_for_logs == "on_pytalk_message":
                await handler_method_on_router(
                    self_event_router,
                    event_primary_obj,
                    *args,
                    connection=connection,
                    **kwargs,
                )
                return

            handler_to_call = getattr(
                self_event_router.pytalk_event_handlers, method_name_on_handler, None
            )
            if handler_to_call and callable(handler_to_call):
                # Pass the connection as the second argument to the handler
                await handler_to_call(event_primary_obj, *args, connection, **kwargs)
            else:
                logger.error(
                    "Decorator: Handler method '%s' not found on PytalkEventHandlers.",
                    method_name_on_handler,
                )
        else:
            logger.warning(
                "Decorator: No active TTConnection for instance %s in Pytalk evt '%s'.",
                tt_instance,
                handler_name_for_logs,
            )

    return wrapper


def _get_tt_instance_from_event(
    event_obj: (
        PytalkServer | PytalkUser | PytalkChannel | TeamTalkMessage | pytalk.UserAccount
    ),
) -> pytalk.TeamTalkInstance | None:
    """Extracts the TeamTalkInstance from a given Pytalk event object."""
    if tt_instance := getattr(event_obj, "teamtalk_instance", None):
        return tt_instance
    if (
        hasattr(event_obj, "server")
        and (server_obj := event_obj.server)
        and (tt_instance := getattr(server_obj, "teamtalk_instance", None))
    ):
        return tt_instance
    if hasattr(event_obj, "teamtalk") and (
        tt_instance := getattr(event_obj, "teamtalk", None)
    ):
        return tt_instance
    return None


class PytalkEventRouter:
    """Routes Pytalk events to the corresponding TeamTalkConnection instance."""

    def __init__(
        self,
        app_container: AsyncContainer,
        tt_bot: pytalk.TeamTalkBot,
        connections: dict[str, TeamTalkConnection],
        event_bus: EventBus,
        translator_factory: Callable[[str | None], NullTranslations],
        pytalk_event_handlers: PytalkEventHandlers,
    ) -> None:
        """Initializes the PytalkEventRouter."""
        self.app_container = app_container
        self.tt_bot = tt_bot
        self.connections = connections
        self.event_bus = event_bus
        self.translator_factory = translator_factory
        self.pytalk_event_handlers = pytalk_event_handlers
        self.logger = logging.getLogger(__name__)
        self._register_pytalk_event_handlers()
        self.logger.debug(
            "PytalkEventRouter initialized and Pytalk event handlers registered."
        )

    def _register_pytalk_event_handlers(self) -> None:
        """Registers Pytalk event handlers with the PytalkBot instance."""
        event_handlers_map = {
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

    @route_event_to_connection
    async def on_pytalk_my_login(self, server: PytalkServer) -> None:
        """Routes the bot's own login event."""

    @route_event_to_connection
    async def on_pytalk_user_join(
        self, user: PytalkUser, channel: PytalkChannel
    ) -> None:
        """Routes a user join event."""

    @route_event_to_connection
    async def on_pytalk_my_connection_lost(self, server: PytalkServer) -> None:
        """Routes a connection lost event for the bot."""

    @route_event_to_connection
    async def on_pytalk_my_kicked_from_channel(
        self, channel_obj: PytalkChannel
    ) -> None:
        """Routes a kicked from channel event for the bot."""

    @route_event_to_connection
    async def on_pytalk_message(
        self, message: TeamTalkMessage, connection: TeamTalkConnection
    ) -> None:
        """Handles an incoming message event for a specific connection."""
        async with self.app_container(
            context={TeamTalkMessage: message, TeamTalkConnection: connection}
        ) as request_container:
            message_handler = await request_container.get(MessageHandler)
            await message_handler.route_message(message)

    @route_event_to_connection
    async def on_pytalk_user_login(self, user: PytalkUser) -> None:
        """Routes a user login event."""

    @route_event_to_connection
    async def on_pytalk_user_logout(self, user: PytalkUser) -> None:
        """Routes a user logout event."""

    @route_event_to_connection
    async def on_pytalk_user_update(self, user: PytalkUser) -> None:
        """Routes a user update event."""

    @route_event_to_connection
    async def on_pytalk_user_account_new(self, account: pytalk.UserAccount) -> None:
        """Routes a new user account event."""

    @route_event_to_connection
    async def on_pytalk_user_account_remove(self, account: pytalk.UserAccount) -> None:
        """Routes a removed user account event."""
