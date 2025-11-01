"""Manages a single connection to a TeamTalk server, including state and caches."""

import logging
from typing import TYPE_CHECKING

from pytalk.enums import TeamTalkServerInfo as PytalkTeamTalkServerInfo

if TYPE_CHECKING:
    import pytalk

from bot.config import Settings
from bot.event_bus.bus import EventBus
from bot.teamtalk_bot.cache import TeamTalkCache
from bot.teamtalk_bot.connection_manager import TeamTalkConnectionManager

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


class TeamTalkConnection:
    """Manages the state of a single connection to a TeamTalk server."""

    def __init__(
        self,
        server_info: PytalkTeamTalkServerInfo,
        settings: Settings,
        event_bus: EventBus,
        # These components will be injected by dishka
        connection_manager: TeamTalkConnectionManager,
        cache_manager: TeamTalkCache,
    ) -> None:
        """Initializes a TeamTalkConnection instance."""
        self.server_info = server_info
        self.settings = settings
        self.event_bus = event_bus
        self.connection_manager = connection_manager
        self.cache_manager = cache_manager

        # Set back-references to break circular dependencies at creation time
        self.connection_manager.set_connection(self)
        self.cache_manager.set_connection(self)

        self.instance: pytalk.instance.TeamTalkInstance | None = None
        self.login_complete_time: datetime | None = None
        self._is_finalized = False

    def connect(self) -> bool:
        """Establishes a connection to the TeamTalk server."""
        return self.connection_manager.connect()

    async def disconnect_instance(self) -> None:
        """Disconnects the TeamTalk instance and cleans up resources."""
        await self.connection_manager.disconnect_instance()

    @property
    def is_ready(self) -> bool:
        """Checks if instance is connected and logged in."""
        return (
            self.instance is not None
            and self.instance.connected
            and self.instance.logged_in
        )

    @property
    def is_finalized(self) -> bool:
        """Checks if login sequence has been finalized."""
        return self._is_finalized

    def mark_finalized(self, *, status: bool = True) -> None:
        """Marks the login sequence as finalized or not."""
        self._is_finalized = status
        logger.debug(
            "[%s] Connection state changed to: %s.",
            self.server_info.host,
            "finalized" if status else "NOT finalized",
        )
