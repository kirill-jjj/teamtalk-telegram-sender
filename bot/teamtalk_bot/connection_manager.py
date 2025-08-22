"""Manages the lifecycle of TeamTalk server connections."""

import contextlib
import logging
from typing import TYPE_CHECKING

import pytalk

if TYPE_CHECKING:
    from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)


class TeamTalkConnectionManager:
    """Handles connection/disconnection logic for a TeamTalkConnection."""

    def __init__(self, pytalk_bot: pytalk.TeamTalkBot) -> None:
        """Initializes the TeamTalkConnectionManager."""
        self.pytalk_bot = pytalk_bot
        self.connection: TeamTalkConnection | None = None

    def set_connection(self, connection: "TeamTalkConnection") -> None:
        """Sets the connection context after initialization to avoid circular deps."""
        self.connection = connection

    def connect(self) -> bool:
        """Establishes a connection to the TeamTalk server."""
        if not self.connection:
            logger.error("ConnectionManager: connect called before connection was set.")
            return False

        conn = self.connection
        logger.info(
            "Adding server %s:%s to PytalkBot.",
            conn.server_info.host,
            conn.server_info.tcp_port,
        )
        try:
            # Logic from pytalk.bot.TeamTalkBot.add_server
            tt_instance = pytalk.instance.TeamTalkInstance(
                self.pytalk_bot, conn.server_info
            )

            # Blocking calls
            if not tt_instance.connect():
                return False
            if not tt_instance.login():
                return False

            # Success
            self.pytalk_bot.teamtalks.append(tt_instance)
            conn.instance = tt_instance
            conn.mark_finalized(status=False)
            conn.login_complete_time = None

        except Exception:
            logger.exception("Failed to add and connect server.")
            return False
        else:
            return True

    async def disconnect_instance(self) -> None:
        """Disconnects the TeamTalk instance and cleans up resources."""
        if not self.connection:
            logger.error(
                "ConnectionManager: disconnect_instance called "
                "before connection was set."
            )
            return

        conn = self.connection
        await conn.cache_manager.stop_background_tasks()
        if conn.instance:
            with contextlib.suppress(Exception):
                if conn.instance.logged_in:
                    conn.instance.logout()
                if conn.instance.connected:
                    conn.instance.disconnect()
        conn.mark_finalized(status=False)
        conn.login_complete_time = None

    async def initiate_reconnect(self) -> None:
        """Initiates a reconnection sequence for this connection."""
        await self.disconnect_instance()
        await self.connect()
