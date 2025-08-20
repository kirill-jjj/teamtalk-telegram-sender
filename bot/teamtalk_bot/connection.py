"""Manages a single connection to a TeamTalk server, including state and caches."""

from collections.abc import Callable
import datetime as dt
from datetime import datetime
from gettext import NullTranslations
import logging

from dishka import AsyncContainer
import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.enums import Status as PytalkStatus
from pytalk.enums import TeamTalkServerInfo as PytalkTeamTalkServerInfo
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser

from bot.config import Settings
from bot.constants import (
    INVALID_CHANNEL_ID,
)
from bot.event_bus.bus import EventBus
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.cache import TeamTalkCache
from bot.teamtalk_bot.connection_manager import TeamTalkConnectionManager
from bot.teamtalk_bot.message_handler import MessageHandler

logger = logging.getLogger(__name__)


class TeamTalkConnection:
    """Manages the state of a single connection to a TeamTalk server."""

    def __init__(
        self,
        server_info: PytalkTeamTalkServerInfo,
        pytalk_bot: pytalk.TeamTalkBot,
        settings: Settings,
        dishka_container: AsyncContainer,
        cache: CacheService,
        translator_factory: Callable[[str], NullTranslations],
        event_bus: EventBus,
        message_handler: MessageHandler | None = None,
    ) -> None:
        """Initializes a TeamTalkConnection instance."""
        self.server_info = server_info
        self.pytalk_bot = pytalk_bot
        self.settings = settings
        self.dishka_container = dishka_container
        self.cache = cache
        self.translator_factory = translator_factory
        self.event_bus = event_bus
        self.instance: pytalk.instance.TeamTalkInstance | None = None
        self.login_complete_time: datetime | None = None
        self._is_finalized = False
        self.ttstr = pytalk.instance.sdk.ttstr
        self.cache_manager = TeamTalkCache(self)
        self.connection_manager = TeamTalkConnectionManager(self)
        self.message_handler = message_handler

    async def connect(self) -> bool:
        """Establishes a connection to the TeamTalk server."""
        return await self.connection_manager.connect()

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

    async def _finalize_bot_login_sequence(self, channel: PytalkChannel) -> None:
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

    async def _initiate_reconnect(self) -> None:
        """Initiates a reconnection sequence for this connection."""
        await self.connection_manager.initiate_reconnect()

    async def _determine_target_channel(self) -> tuple[int, str]:
        """Determines the target channel ID and name from config."""
        if not self.instance:
            return INVALID_CHANNEL_ID, ""

        cfg_tt = self.settings.teamtalk
        chan_path = cfg_tt.channel
        target_chan_name = chan_path
        final_chan_id = INVALID_CHANNEL_ID

        if chan_path.isdigit():
            final_chan_id = int(chan_path)
            ch_obj = self.instance.get_channel(final_chan_id)
            if ch_obj:
                target_chan_name = self.ttstr(ch_obj.name)
            else:  # Channel ID specified but not found
                logger.warning(
                    "[%s] Channel ID '%s' not found.", self.server_info.host, chan_path
                )
                final_chan_id = INVALID_CHANNEL_ID  # Reset if not found
        else:
            ch_obj = self.instance.get_channel_from_path(chan_path)
            if ch_obj:
                final_chan_id = ch_obj.id
                target_chan_name = self.ttstr(ch_obj.name)
            else:
                logger.error(
                    "[%s] Channel path '%s' not found.",
                    self.server_info.host,
                    chan_path,
                )
        return final_chan_id, target_chan_name

    async def _join_configured_channel(self) -> None:
        """Joins the configured TeamTalk channel."""
        if not self.instance:
            logger.error("[%s] No instance to join channel.", self.server_info.host)
            await self._initiate_reconnect()
            return

        final_chan_id, target_chan_name = await self._determine_target_channel()
        chan_pass = self.settings.teamtalk.channel_password or ""

        try:
            if final_chan_id != INVALID_CHANNEL_ID:
                logger.info(
                    "[%s] Joining chan: '%s' (ID: %s).",
                    self.server_info.host,
                    target_chan_name,
                    final_chan_id,
                )
                self.instance.join_channel_by_id(final_chan_id, password=chan_pass)
            else:
                logger.warning(
                    "[%s] No valid target channel found/configured. "
                    "Staying in default channel.",
                    self.server_info.host,
                )
                # If not joining a specific channel, finalize with the current one.
                curr_chan_id = self.instance.getMyCurrentChannelID()
                ch_to_finalize = self.instance.get_channel(
                    curr_chan_id if curr_chan_id is not None else 0
                )
                if ch_to_finalize:
                    await self._finalize_bot_login_sequence(ch_to_finalize)
                else:
                    logger.warning(
                        "[%s] Could not get current/root channel to finalize.",
                        self.server_info.host,
                    )

        except pytalk.exceptions.PermissionError:
            logger.exception(
                "[%s] PermissionError joining '%s'. Will try to finalize in "
                "current/default channel.",
                self.server_info.host,
                target_chan_name,
            )
            # Attempt to finalize in the current channel if join failed
            # due to permissions
            curr_chan_id_after_fail = self.instance.getMyCurrentChannelID()
            ch_id_to_get = (
                curr_chan_id_after_fail if curr_chan_id_after_fail is not None else 0
            )
            ch_to_finalize_after_fail = self.instance.get_channel(ch_id_to_get)
            if ch_to_finalize_after_fail:
                await self._finalize_bot_login_sequence(ch_to_finalize_after_fail)
            else:
                logger.exception(  # In except block, so changed from error to exception
                    "[%s] Could not get current channel (ID: %s) to finalize "
                    "after permission error.",
                    self.server_info.host,
                    ch_id_to_get,
                )

        except Exception:
            logger.exception(
                "[%s] Error during channel join/finalization.", self.server_info.host
            )
            await self._initiate_reconnect()

    async def on_my_login(self, server: PytalkServer) -> None:
        """Handles the bot's own login event for this connection."""
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
            await self._initiate_reconnect()  # Attempt to recover
            return

        logger.info(
            "[%s] Logged in to TT. Instance: %s",
            self.server_info.host,
            self.instance,
        )
        await self._join_configured_channel()

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
                await self._finalize_bot_login_sequence(channel)
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
        await self._initiate_reconnect()

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
        await self._initiate_reconnect()

    async def on_message(self, message: TeamTalkMessage) -> None:
        """Handles an incoming message on this server connection."""
        if self.message_handler:
            await self.message_handler.route_message(message)

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
