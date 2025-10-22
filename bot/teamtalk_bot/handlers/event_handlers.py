"""Handlers for raw pytalk events.

This module separates the logic of handling events from the TeamTalk server
from the connection state management.
"""

from __future__ import annotations

from collections.abc import Callable
import datetime as dt
from datetime import datetime
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.enums import Status as PytalkStatus
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser

from bot.event_bus.bus import EventBus
from bot.teamtalk_bot.enums import PytalkEvent
from bot.teamtalk_bot.events import UserJoinedEvent, UserLeftEvent
from bot.teamtalk_bot.formatters import (
    get_effective_server_name,
    get_tt_user_display_name,
)

if TYPE_CHECKING:
    from bot.teamtalk_bot.connection import TeamTalkConnection


logger = logging.getLogger(__name__)


class PytalkEventHandlers:
    """Handles events dispatched from the PytalkEventRouter."""

    def __init__(
        self,
        event_bus: EventBus,
        translator_factory: Callable[[str | None], NullTranslations],
    ) -> None:
        """Initializes the PytalkEventHandlers."""
        self.ttstr = pytalk.instance.sdk.ttstr
        self.event_bus = event_bus
        self.translator_factory = translator_factory

    async def _publish_user_event(
        self,
        user: PytalkUser,
        connection: TeamTalkConnection,
        event_class: type[UserJoinedEvent] | type[UserLeftEvent],
    ) -> None:
        """Generic helper to publish user-related domain events."""
        if not connection.instance or not connection.is_ready:
            return

        if event_class is UserJoinedEvent and not connection.is_finalized:
            logger.debug(
                "Ignoring initial user joined event for %s (connection not finalized).",
                connection.ttstr(user.username),
            )
            return

        translator = self.translator_factory(connection.settings.general.default_lang)
        server_name = get_effective_server_name(
            connection.instance, translator, connection.settings
        )
        user_display_name = get_tt_user_display_name(user, translator)

        event = event_class(
            user_nickname=user_display_name,
            username=connection.ttstr(user.username),
            user_id=user.id,
            server_name=server_name,
            online_users_cache=connection.cache_manager.online_users_cache,
        )
        await self.event_bus.publish(event)

    @staticmethod
    async def on_my_login(server: PytalkServer, connection: TeamTalkConnection) -> None:
        """Handles the bot's own login event for a connection."""
        logger.info("[%s] on_my_login event received.", connection.server_info.host)
        _ = server  # Mark as unused
        connection.login_complete_time = None
        connection.mark_finalized(status=False)

        if connection.instance:
            try:
                if connection.instance.server.get_properties():
                    pass  # Properties fetched, but not used for now
            except Exception as e:
                logger.warning(
                    "[%s] Error getting server props: %s",
                    connection.server_info.host,
                    e,
                )
        else:
            logger.error(
                "[%s] No instance available at start of on_my_login.",
                connection.server_info.host,
            )
            await connection.connection_manager.initiate_reconnect()
            return

        logger.info(
            "[%s] Logged in to TT. Instance: %s",
            connection.server_info.host,
            connection.instance,
        )
        await connection.connection_manager.join_configured_channel()

    async def on_user_join(
        self, user: PytalkUser, channel: PytalkChannel, connection: TeamTalkConnection
    ) -> None:
        """Handles another user joining a channel on this server connection."""
        connection.cache_manager.update_caches_on_event(PytalkEvent.USER_JOIN, user)
        if not connection.instance:
            logger.error(
                "[%s] No instance in on_user_join.", connection.server_info.host
            )
            return

        my_user_id = connection.instance.getMyUserID()
        if my_user_id is None:
            logger.error(
                "[%s] Failed to get bot's ID in on_user_join.",
                connection.server_info.host,
            )
            return

        if user.id == my_user_id:
            if not connection.is_finalized:
                await self.finalize_bot_login_sequence(channel, connection)
            else:
                logger.info(
                    "[%s] Bot re-joined chan %s (finalized).",
                    connection.server_info.host,
                    self.ttstr(channel.name),
                )

    async def on_user_login(
        self, user: PytalkUser, connection: TeamTalkConnection
    ) -> None:
        """Handles user login, updates cache, and publishes a domain event."""
        connection.cache_manager.update_caches_on_event(PytalkEvent.USER_LOGIN, user)
        await self._publish_user_event(user, connection, UserJoinedEvent)

    async def on_user_logout(
        self, user: PytalkUser, connection: TeamTalkConnection
    ) -> None:
        """Handles user logout, publishes a domain event, and then updates cache."""
        await self._publish_user_event(user, connection, UserLeftEvent)
        connection.cache_manager.update_caches_on_event(PytalkEvent.USER_LOGOUT, user)

    @staticmethod
    async def on_my_connection_lost(
        server: PytalkServer, connection: TeamTalkConnection
    ) -> None:
        """Handles disconnection from the server for this connection."""
        _ = server  # Mark as unused
        logger.warning(
            "[%s] Connection lost. Reconnecting...", connection.server_info.host
        )
        connection.mark_finalized(status=False)
        connection.login_complete_time = None
        await connection.cache_manager.stop_background_tasks()
        await connection.connection_manager.initiate_reconnect()

    async def on_my_kicked_from_channel(
        self, channel_obj: PytalkChannel, connection: TeamTalkConnection
    ) -> None:
        """Handles being kicked from a channel on this server connection."""
        ch_name = (
            self.ttstr(channel_obj.name)
            if channel_obj and channel_obj.name
            else "Unknown"
        )
        logger.warning(
            "[%s] Kicked from chan '%s'. Reconnecting...",
            connection.server_info.host,
            ch_name,
        )
        connection.mark_finalized(status=False)
        connection.login_complete_time = None
        await connection.cache_manager.stop_background_tasks()
        await connection.connection_manager.initiate_reconnect()

    @staticmethod
    async def on_user_update(user: PytalkUser, connection: TeamTalkConnection) -> None:
        """Handles updates to a user's information on this server connection."""
        connection.cache_manager.update_caches_on_event(PytalkEvent.USER_UPDATE, user)

    @staticmethod
    async def on_user_account_new(
        account: pytalk.UserAccount, connection: TeamTalkConnection
    ) -> None:
        """Handles a new user account being created on this server."""
        connection.cache_manager.update_caches_on_event(
            PytalkEvent.USER_ACCOUNT_NEW, account
        )

    @staticmethod
    async def on_user_account_remove(
        account: pytalk.UserAccount, connection: TeamTalkConnection
    ) -> None:
        """Handles a user account being removed from this server."""
        connection.cache_manager.update_caches_on_event(
            PytalkEvent.USER_ACCOUNT_REMOVE, account
        )

    async def finalize_bot_login_sequence(
        self, channel: PytalkChannel, connection: TeamTalkConnection
    ) -> None:
        """Finalizes the bot's login sequence for a connection."""
        if connection.is_finalized:
            logger.info(
                "[%s] Login sequence already finalized. Skipping.",
                connection.server_info.host,
            )
            return
        if not connection.instance:
            logger.error(
                "[%s] No instance to finalize login.", connection.server_info.host
            )
            return

        ch_name = (
            self.ttstr(channel.name)
            if hasattr(channel, "name") and channel.name
            else "Unknown"
        )
        logger.info(
            "[%s] Bot in channel: %s. Finalizing login...",
            connection.server_info.host,
            ch_name,
        )

        logger.info(
            "[%s] Initial online users cache population...", connection.server_info.host
        )
        connection.cache_manager.start_background_tasks()
        try:
            gender = connection.settings.general.gender.lower()
            status_val = PytalkStatus.online.neutral
            if gender == "male":
                status_val = PytalkStatus.online.male
            elif gender == "female":
                status_val = PytalkStatus.online.female

            status_text = connection.settings.teamtalk.status_text
            connection.instance.change_status(status_val, status_text)
            connection.login_complete_time = datetime.now(dt.UTC)
            connection.mark_finalized(status=True)
            logger.info(
                "[%s] Login finalized at %s.",
                connection.server_info.host,
                connection.login_complete_time,
            )
        except Exception:
            logger.exception(
                "[%s] Error finalizing login (status/time).",
                connection.server_info.host,
            )
