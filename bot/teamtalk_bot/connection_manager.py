"""Manages the lifecycle of TeamTalk server connections."""

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)


class TeamTalkConnectionManager:
    """Handles connection/disconnection logic for a TeamTalkConnection."""

    def __init__(self, connection: "TeamTalkConnection") -> None:
        """Initializes the TeamTalkConnectionManager."""
        self.connection = connection

    async def connect(self) -> bool:
        """Establishes a connection to the TeamTalk server."""
        conn = self.connection
        logger.info(
            "Adding server %s:%s to PytalkBot.",
            conn.server_info.host,
            conn.server_info.tcp_port,
        )
        try:
            num_instances_before = len(conn.pytalk_bot.teamtalks)
            await conn.pytalk_bot.add_server(conn.server_info)
            num_instances_after = len(conn.pytalk_bot.teamtalks)
            if num_instances_after > num_instances_before:
                conn.instance = conn.pytalk_bot.teamtalks[-1]
                conn.mark_finalized(status=False)
                conn.login_complete_time = None
            else:
                return False
        except Exception:
            return False
        else:
            return True

    async def disconnect_instance(self) -> None:
        """Disconnects the TeamTalk instance and cleans up resources."""
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
