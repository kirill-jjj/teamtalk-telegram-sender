"""Manages the lifecycle of TeamTalk server connections."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import pytalk

from bot.constants import INVALID_CHANNEL_ID

if TYPE_CHECKING:
    from bot.teamtalk_bot.connection import TeamTalkConnection
    from bot.teamtalk_bot.handlers.event_handlers import PytalkEventHandlers

logger = logging.getLogger(__name__)


class TeamTalkConnectionManager:
    """Handles connection/disconnection logic for a TeamTalkConnection."""

    def __init__(
        self, pytalk_bot: pytalk.TeamTalkBot, pytalk_event_handlers: PytalkEventHandlers
    ) -> None:
        """Initializes the TeamTalkConnectionManager."""
        self.pytalk_bot = pytalk_bot
        self.pytalk_event_handlers = pytalk_event_handlers
        self.connection: TeamTalkConnection | None = None

    def set_connection(self, connection: TeamTalkConnection) -> None:
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
            # Assign the instance to the connection object *before* connecting
            conn.instance = tt_instance

            # Blocking calls
            if not tt_instance.connect():
                return False
            if not tt_instance.login():
                return False

            # Success
            self.pytalk_bot.teamtalks.append(tt_instance)
            conn.mark_finalized(status=False)
            conn.login_complete_time = None

        except pytalk.exceptions.TeamTalkException as e:
            logger.critical("Failed to connect or login to TeamTalk server: %s", e)
            return False
        except OSError:
            logger.exception(
                "An unexpected error occurred while connecting to the server."
            )
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

    async def determine_target_channel(self) -> tuple[int, str]:
        """Determines the target channel ID and name from config."""
        conn = self.connection
        if not conn or not conn.instance:
            return INVALID_CHANNEL_ID, ""

        instance = conn.instance
        cfg_tt = conn.settings.teamtalk
        chan_path = cfg_tt.channel
        target_chan_name = chan_path
        final_chan_id = INVALID_CHANNEL_ID

        if chan_path.isdigit():
            final_chan_id = int(chan_path)
            ch_obj = instance.get_channel(final_chan_id)
            if ch_obj:
                target_chan_name = conn.ttstr(ch_obj.name)
            else:  # Channel ID specified but not found
                logger.warning(
                    "[%s] Channel ID '%s' not found.", conn.server_info.host, chan_path
                )
                final_chan_id = INVALID_CHANNEL_ID  # Reset if not found
        else:
            ch_obj = instance.get_channel_from_path(chan_path)
            if ch_obj:
                final_chan_id = ch_obj.id
                target_chan_name = conn.ttstr(ch_obj.name)
            else:
                logger.error(
                    "[%s] Channel path '%s' not found.",
                    conn.server_info.host,
                    chan_path,
                )
        return final_chan_id, target_chan_name

    async def join_configured_channel(self) -> None:
        """Joins the configured TeamTalk channel."""
        conn = self.connection
        if not conn or not conn.instance:
            return await self._handle_no_instance(conn, None)

        instance = conn.instance
        try:
            await self._try_join_channel(conn, instance)
        except pytalk.exceptions.PermissionError as e:
            await self._handle_join_permission_error(conn, instance, e)
        except (pytalk.exceptions.TeamTalkException, ValueError, OSError) as e:
            await self._handle_generic_join_error(conn, e)

    @staticmethod
    async def _handle_no_instance(
        conn: TeamTalkConnection | None,
        _instance: pytalk.TeamTalkInstance | None,
    ) -> None:
        """Handles the case where there is no connection or instance."""

    async def _try_join_channel(
        self, conn: TeamTalkConnection, instance: pytalk.TeamTalkInstance
    ) -> None:
        """Tries to join the configured channel."""
        final_chan_id, target_chan_name = await self.determine_target_channel()
        chan_pass = conn.settings.teamtalk.channel_password or ""

        if final_chan_id != INVALID_CHANNEL_ID:
            logger.info(
                "[%s] Joining chan: '%s' (ID: %s).",
                conn.server_info.host,
                target_chan_name,
                final_chan_id,
            )
            instance.join_channel_by_id(final_chan_id, password=chan_pass)
        else:
            await self._handle_no_target_channel(conn, instance)

    async def _handle_no_target_channel(
        self, conn: TeamTalkConnection, instance: pytalk.TeamTalkInstance
    ) -> None:
        """Handles the case where no valid target channel is found."""
        logger.warning(
            "[%s] No valid target channel found/configured. "
            "Staying in default channel.",
            conn.server_info.host,
        )
        curr_chan_id = instance.getMyCurrentChannelID()
        ch_to_finalize = instance.get_channel(
            curr_chan_id if curr_chan_id is not None else 0
        )
        if ch_to_finalize:
            await self.pytalk_event_handlers.finalize_bot_login_sequence(
                ch_to_finalize, conn
            )
        else:
            logger.warning(
                "[%s] Could not get current/root channel to finalize.",
                conn.server_info.host,
            )

    async def _handle_join_permission_error(
        self,
        conn: TeamTalkConnection,
        instance: pytalk.TeamTalkInstance,
        _error: pytalk.exceptions.PermissionError,
    ) -> None:
        """Handles a permission error when joining a channel."""
        _, target_chan_name = await self.determine_target_channel()
        logger.error(
            "[%s] PermissionError joining '%s'. Will try to finalize in "
            "current/default channel.",
            conn.server_info.host,
            target_chan_name,
        )
        curr_chan_id_after_fail = instance.getMyCurrentChannelID()
        ch_id_to_get = (
            curr_chan_id_after_fail if curr_chan_id_after_fail is not None else 0
        )
        ch_to_finalize_after_fail = instance.get_channel(ch_id_to_get)
        if ch_to_finalize_after_fail:
            await self.pytalk_event_handlers.finalize_bot_login_sequence(
                ch_to_finalize_after_fail, conn
            )
        else:
            logger.error(
                "[%s] Could not get current channel (ID: %s) to finalize "
                "after permission error.",
                conn.server_info.host,
                ch_id_to_get,
            )

    @staticmethod
    async def _handle_generic_join_error(
        conn: TeamTalkConnection, _error: Exception
    ) -> None:
        """Handles a generic error during channel join."""
        logger.error(
            "[%s] Error during channel join/finalization.", conn.server_info.host
        )
