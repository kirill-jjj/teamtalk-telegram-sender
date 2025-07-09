"""Handles events received from the Pytalk (TeamTalk) library by routing them to the appropriate TeamTalkConnection."""

import logging
from typing import TYPE_CHECKING

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

    async def on_pytalk_my_login(self, server: PytalkServer) -> None:
        """Routes the bot's own login event to the appropriate connection."""
        connection = self._get_connection_by_instance(server.teamtalk_instance)
        if connection:
            await connection.on_my_login(server)
        else:
            logger.error("MyLogin: No connection for instance %s", server.teamtalk_instance)

    async def on_pytalk_user_join(self, user: PytalkUser, channel: PytalkChannel) -> None:
        """Routes a user join event to the appropriate connection."""
        tt_instance = getattr(user, "teamtalk_instance", None) or (
            hasattr(user, "server") and getattr(user.server, "teamtalk_instance", None)
        )
        if not tt_instance:
            logger.error("UserJoin: Cannot determine instance for user %s", user.username)
            return
        connection = self._get_connection_by_instance(tt_instance)
        if connection:
            await connection.on_user_join(user, channel)
        else:
            logger.error("UserJoin: No connection for instance %s", tt_instance)

    async def on_pytalk_my_connection_lost(self, server: PytalkServer) -> None:
        """Routes a connection lost event for the bot to the appropriate connection."""
        connection = self._get_connection_by_instance(server.teamtalk_instance)
        if connection:
            await connection.on_my_connection_lost(server)
        else:
            logger.warning("ConnectionLost: No conn by instance for %s. Trying by server info.", server)
            if server and server.info:
                conn_by_info = self._get_connection_by_server_info(server.info)
                if conn_by_info:
                    await conn_by_info.on_my_connection_lost(server)
                else:
                    logger.error("ConnectionLost: Still no conn for %s:%s", server.info.host, server.info.tcp_port)
            else:
                logger.error("ConnectionLost: server or server.info is None.")

    async def on_pytalk_my_kicked_from_channel(self, channel_obj: PytalkChannel) -> None:
        """Routes a kicked from channel event for the bot to the appropriate connection."""
        connection = self._get_connection_by_instance(channel_obj.teamtalk)
        if connection:
            await connection.on_my_kicked_from_channel(channel_obj)
        else:
            logger.error("Kicked: No connection for instance %s", channel_obj.teamtalk)

    async def on_pytalk_message(self, message: TeamTalkMessage) -> None:
        """Routes an incoming message event to the appropriate connection."""
        connection = self._get_connection_by_instance(message.teamtalk_instance)
        if connection:
            await connection.on_message(message)
        else:
            logger.error("Message: No connection for instance %s", message.teamtalk_instance)

    async def on_pytalk_user_login(self, user: PytalkUser) -> None:
        """Routes a user login event to the appropriate connection."""
        tt_instance = getattr(user, "teamtalk_instance", None) or (
            hasattr(user, "server") and getattr(user.server, "teamtalk_instance", None)
        )
        if not tt_instance:
            logger.error("UserLogin: Cannot determine instance for user %s", user.username)
            return
        connection = self._get_connection_by_instance(tt_instance)
        if connection:
            await connection.on_user_login(user)
        else:
            logger.error("UserLogin: No connection for instance %s", tt_instance)

    async def on_pytalk_user_logout(self, user: PytalkUser) -> None:
        """Routes a user logout event to the appropriate connection."""
        tt_instance = getattr(user, "teamtalk_instance", None) or (
            hasattr(user, "server") and getattr(user.server, "teamtalk_instance", None)
        )
        if not tt_instance:
            logger.error("UserLogout: Cannot determine instance for user %s", user.username)
            return
        connection = self._get_connection_by_instance(tt_instance)
        if connection:
            await connection.on_user_logout(user)
        else:
            logger.error("UserLogout: No connection for instance %s", tt_instance)

    async def on_pytalk_user_update(self, user: PytalkUser) -> None:
        """Routes a user update event to the appropriate connection."""
        tt_instance = getattr(user, "teamtalk_instance", None) or (
            hasattr(user, "server") and getattr(user.server, "teamtalk_instance", None)
        )
        if not tt_instance:
            logger.error("UserUpdate: Cannot determine instance for user %s", user.username)
            return
        connection = self._get_connection_by_instance(tt_instance)
        if connection:
            await connection.on_user_update(user)
        else:
            logger.error("UserUpdate: No connection for instance %s", tt_instance)

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
            for _conn_key, conn_val in self.services.connections.items():
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
            for _conn_key, conn_val in self.services.connections.items():
                await conn_val.on_user_account_remove(account)
