"""Manages a single connection to a TeamTalk server, including state and caches."""

import datetime as dt
from datetime import datetime
import logging

import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.enums import Status as PytalkStatus
from pytalk.enums import TeamTalkServerInfo as PytalkTeamTalkServerInfo
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser

from bot.config import Settings
from bot.event_bus.bus import EventBus
from bot.teamtalk_bot.cache import TeamTalkCache
from bot.teamtalk_bot.connection_manager import TeamTalkConnectionManager

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
        self.ttstr = pytalk.instance.sdk.ttstr

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
        logger.info(
            "[%s] Connection marked: %s.",
            self.server_info.host,
            "finalized" if status else "NOT finalized",
        )

    async def finalize_bot_login_sequence(self, channel: PytalkChannel) -> None:
        """Finalizes the bot's login sequence for this connection."""
        if self.is_finalized:
            logger.info(
                "[%s] Login sequence already finalized. Skipping.",
                self.server_info.host,
            )
            return
        if not self.instance:
            logger.error("[%s] No instance to finalize login.", self.server_info.host)
            return

        ch_name = (
            self.ttstr(channel.name)
            if hasattr(channel, "name") and channel.name
            else "Unknown"
        )
        logger.info(
            "[%s] Bot in channel: %s. Finalizing login...",
            self.server_info.host,
            ch_name,
        )

        logger.info(
            "[%s] Initial online users cache population...", self.server_info.host
        )
        # The cache manager now handles this logic.
        # We can remove the direct implementation.

        self.cache_manager.start_background_tasks()
        try:
            gender = self.settings.general.gender.lower()
            status_val = PytalkStatus.online.neutral
            if gender == "male":
                status_val = PytalkStatus.online.male
            elif gender == "female":
                status_val = PytalkStatus.online.female

            status_text = self.settings.teamtalk.status_text
            self.instance.change_status(status_val, status_text)
            self.login_complete_time = datetime.now(dt.UTC)
            self.mark_finalized(status=True)
            logger.info(
                "[%s] Login finalized at %s.",
                self.server_info.host,
                self.login_complete_time,
            )
        except Exception:
            logger.exception(
                "[%s] Error finalizing login (status/time).", self.server_info.host
            )

    async def on_my_login(self, server: PytalkServer) -> None:
        """Handles the bot's own login event for this connection."""
        logger.info("[%s] on_my_login event received.", self.server_info.host)
        # The 'server' argument is part of Pytalk's event signature but not used here.
        _ = server  # Mark as unused to satisfy linters like Ruff (ARG002)
        self.login_complete_time = None
        self.mark_finalized(status=False)

        if self.instance:
            try:
                props = self.instance.server.get_properties()
                if props:
                    pass

            except Exception as e:
                logger.warning(
                    "[%s] Error getting server props: %s", self.server_info.host, e
                )
        else:  # Should ideally not happen if connect() succeeded
            logger.error(
                "[%s] No instance available at start of on_my_login.",
                self.server_info.host,
            )
            await self.connection_manager.initiate_reconnect()  # Attempt to recover
            return

        logger.info(
            "[%s] Logged in to TT. Instance: %s",
            self.server_info.host,
            self.instance,
        )
        await self.connection_manager.join_configured_channel()

    async def on_user_join(self, user: PytalkUser, channel: PytalkChannel) -> None:
        """Handles another user joining a channel on this server connection."""
        self.cache_manager.update_caches_on_event("user_join", user)
        if not self.instance:
            logger.error("[%s] No instance in on_user_join.", self.server_info.host)
            return
        my_user_id = self.instance.getMyUserID()
        if my_user_id is None:
            logger.error(
                "[%s] Failed to get bot's ID in on_user_join.", self.server_info.host
            )
            return
        if user.id == my_user_id:
            if not self.is_finalized:
                await self.finalize_bot_login_sequence(channel)
            else:
                logger.info(
                    "[%s] Bot re-joined chan %s (finalized).",
                    self.server_info.host,
                    self.ttstr(channel.name),
                )

    async def on_my_connection_lost(self, server: PytalkServer) -> None:
        """Handles disconnection from the server for this connection."""
        # The 'server' argument is part of Pytalk's event signature but not used here.
        _ = server  # Mark as unused
        logger.warning("[%s] Connection lost. Reconnecting...", self.server_info.host)
        self.mark_finalized(status=False)
        self.login_complete_time = None
        await self.cache_manager.stop_background_tasks()
        await self.connection_manager.initiate_reconnect()

    async def on_my_kicked_from_channel(self, channel_obj: PytalkChannel) -> None:
        """Handles being kicked from a channel on this server connection."""
        ch_name = (
            self.ttstr(channel_obj.name)
            if channel_obj and channel_obj.name
            else "Unknown"
        )
        logger.warning(
            "[%s] Kicked from chan '%s'. Reconnecting...",
            self.server_info.host,
            ch_name,
        )
        self.mark_finalized(status=False)
        self.login_complete_time = None
        await self.cache_manager.stop_background_tasks()
        await self.connection_manager.initiate_reconnect()

    async def on_user_update(self, user: PytalkUser) -> None:
        """Handles updates to a user's information on this server connection."""
        self.cache_manager.update_caches_on_event("user_update", user)

    async def on_user_account_new(self, account: pytalk.UserAccount) -> None:
        """Handles a new user account being created on this server."""
        self.cache_manager.update_caches_on_event("user_account_new", account)

    async def on_user_account_remove(self, account: pytalk.UserAccount) -> None:
        """Handles a user account being removed from this server."""
        self.cache_manager.update_caches_on_event("user_account_remove", account)

    def __repr__(self) -> str:
        """Returns a string representation of the TeamTalkConnection object."""
        instance_id = id(self.instance) if self.instance else "N/A"
        return (
            f"<TeamTalkConnection host={self.server_info.host}:"
            f"{self.server_info.tcp_port} "
            f"instance_id={instance_id} finalized={self.is_finalized}>"
        )
