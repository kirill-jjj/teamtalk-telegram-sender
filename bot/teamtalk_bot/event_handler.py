"""Handles events received from the Pytalk (TeamTalk) library."""

from datetime import datetime
import logging
from typing import TYPE_CHECKING

import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.enums import Status as PytalkStatus
from pytalk.exceptions import PermissionError as PytalkPermissionError
from pytalk.exceptions import TeamTalkException
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser

from bot.constants import (
    INVALID_CHANNEL_ID,
    NOTIFICATION_EVENT_JOIN,
    NOTIFICATION_EVENT_LEAVE,
    TEAMTALK_PRIVATE_MESSAGE_TYPE,
)
from bot.core.notifications import send_join_leave_notification_logic
from bot.teamtalk_bot.commands import (
    handle_tt_add_admin_command,
    handle_tt_help_command,
    handle_tt_remove_admin_command,
    handle_tt_subscribe_command,
    handle_tt_unknown_command,
    handle_tt_unsubscribe_command,
)
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.utils import (
    forward_tt_message_to_telegram_admin,
)

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


class TeamTalkEventHandler:
    """Handles events from the Pytalk library and dispatches them to appropriate logic."""

    def __init__(self, services: "Services"):
        """Initializes the TeamTalkEventHandler.

        Args:
            services: The application's services container.
        """
        self.services = services
        self.tt_bot = services.tt_bot
        self._register_pytalk_event_handlers()
        self.services.logger.info("TeamTalkEventHandler initialized and Pytalk event handlers registered.")

    def _register_pytalk_event_handlers(self):
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
        for conn in self.services.connections.values():
            if conn.instance is tt_instance:
                return conn
        self.services.logger.warning("Could not find an active TeamTalkConnection for instance: %s", tt_instance)
        return None

    def _get_connection_by_server_info(self, server_info: pytalk.TeamTalkServerInfo) -> TeamTalkConnection | None:
        server_key = f"{server_info.host}:{server_info.tcp_port}"
        return self.services.connections.get(server_key)

    async def _finalize_bot_login_sequence(self, connection: TeamTalkConnection, channel: PytalkChannel):
        if connection.is_finalized:
            self.services.logger.info("[%s] Login sequence already finalized. Skipping.", connection.server_info.host)
            return

        if not connection.instance:
            self.services.logger.error(
                "[%s] Cannot finalize login sequence: instance not available in connection object.",
                connection.server_info.host,
            )
            return

        tt_instance = connection.instance
        if hasattr(channel, "name") and isinstance(channel.name, bytes):
            channel_name_display = pytalk.instance.sdk.ttstr(channel.name)
        else:
            channel_name_display = str(channel.name)
        self.services.logger.info(
            "[%s] Bot successfully joined channel: %s. Finalizing login sequence...",
            connection.server_info.host,
            channel_name_display,
        )

        self.services.logger.info(
            "[%s] Performing initial population of online users cache...", connection.server_info.host
        )
        try:
            initial_online_users = tt_instance.server.get_users()
            connection.online_users_cache.clear()
            for u in initial_online_users:
                if hasattr(u, "id"):
                    connection.online_users_cache[u.id] = u
            self.services.logger.info(
                "[%s] Online users cache initialized with %s users.",
                connection.server_info.host,
                len(connection.online_users_cache),
            )
        except Exception as e:
            self.services.logger.exception(
                "[%s] Error during initial online users cache population: %s",
                connection.server_info.host,
                e,
            )

        connection.start_background_tasks()

        try:
            gender = self.services.config.general.gender.lower()
            status_val = PytalkStatus.online.neutral
            if gender == "male":
                status_val = PytalkStatus.online.male
            elif gender == "female":
                status_val = PytalkStatus.online.female

            tt_instance.change_status(status_val, self.services.config.teamtalk.status_text)
            connection.login_complete_time = datetime.utcnow()
            connection.mark_finalized(True)
            self.services.logger.debug(
                "[%s] TeamTalk status set to: '%s'.",
                connection.server_info.host,
                self.services.config.teamtalk.status_text,
            )
            self.services.logger.info(
                "[%s] TeamTalk login sequence finalized at %s.",
                connection.server_info.host,
                connection.login_complete_time,
            )
        except Exception as e:
            self.services.logger.exception(
                "[%s] Error setting status or login_complete_time for bot: %s",
                connection.server_info.host,
                e,
            )

    async def _initiate_reconnect_for_connection(self, connection: TeamTalkConnection):
        if not connection:
            self.services.logger.error("Reconnect requested for a null connection object.")
            return

        server_key = f"{connection.server_info.host}:{connection.server_info.tcp_port}"  # f-string for key is fine
        self.services.logger.info("[%s] Starting reconnection logic.", server_key)

        await connection.disconnect_instance()

        self.services.logger.info("[%s] Attempting to re-establish connection...", server_key)
        if await connection.connect():
            self.services.logger.info("[%s] Reconnect attempt initiated. Waiting for login events.", server_key)
        else:
            self.services.logger.error("[%s] Failed to re-initiate connection via connection.connect().", server_key)

    async def on_pytalk_ready(self):
        """Handles the Pytalk `on_ready` event.

        This is called when the PytalkBot instance is ready to start adding servers.
        It initializes the primary TeamTalk server connection based on config.
        """
        # PLR0912 (Too many branches) and PLR0915 (Too many statements) are suppressed here
        # as this function orchestrates a complex login and channel join sequence with multiple
        # potential points of failure or alternative paths. Refactoring into smaller helpers
        # was attempted but led to persistent diff application issues.
        # Manual review and refactoring may be beneficial if further simplification is required.
        self.services.logger.info("TeamTalkEventHandler: Pytalk Bot is ready. Initializing TeamTalk connections...")
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
        server_key = f"{pytalk_server_info.host}:{pytalk_server_info.tcp_port}"  # f-string for key is fine

        if server_key in self.services.connections:
            self.services.logger.warning("Connection for %s already exists. Reconnecting.", server_key)
            await self.services.connections[server_key].disconnect_instance()

        connection = TeamTalkConnection(
            server_info=pytalk_server_info,
            pytalk_bot=self.tt_bot,
            session_factory=self.services.session_factory,
            app_config=self.services.config,
        )
        self.services.connections[server_key] = connection

        self.services.logger.info("Attempting to connect TeamTalkConnection for %s...", server_key)
        if not await connection.connect():
            self.services.logger.error(
                "Failed to initiate connection for %s via TeamTalkConnection.connect().", server_key
            )
        else:
            self.services.logger.info("TeamTalkConnection for %s initiated. Waiting for login events.", server_key)

    async def on_pytalk_my_login(self, server: PytalkServer):  # noqa: PLR0912, PLR0915
        """Handles the event when the bot successfully logs into a TeamTalk server."""
        tt_instance = server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)

        if not connection:
            self.services.logger.error(
                "on_pytalk_my_login: Received login event for unknown instance: %s. Server: %s",
                tt_instance,
                server.info.host,
            )
            return

        connection.login_complete_time = None
        connection.mark_finalized(False)

        server_name_display = "Unknown Server"
        try:
            server_props = tt_instance.server.get_properties()
            if server_props:
                server_name_display = pytalk.instance.sdk.ttstr(server_props.server_name)
        except Exception as e:
            self.services.logger.warning(
                "[%s] Error getting server properties on login: %s", connection.server_info.host, e
            )

        self.services.logger.info(
            "[%s] Successfully logged in to TeamTalk server: %s (Host: %s). Current instance: %s",
            connection.server_info.host,
            server_name_display,
            server.info.host,
            connection.instance,
        )

        try:
            channel_id_or_path = self.services.config.teamtalk.channel
            channel_password = self.services.config.teamtalk.channel_password or ""
            target_channel_name_log = channel_id_or_path

            final_channel_id = INVALID_CHANNEL_ID
            if channel_id_or_path.isdigit():
                final_channel_id = int(channel_id_or_path)
                chan_obj_log = tt_instance.get_channel(final_channel_id)
                if chan_obj_log:
                    target_channel_name_log = pytalk.instance.sdk.ttstr(chan_obj_log.name)
            else:
                channel_obj = tt_instance.get_channel_from_path(channel_id_or_path)
                if channel_obj:
                    final_channel_id = channel_obj.id
                    target_channel_name_log = pytalk.instance.sdk.ttstr(channel_obj.name)
                else:
                    self.services.logger.error(
                        "[%s] Channel path '%s' not found during login.",
                        connection.server_info.host,
                        channel_id_or_path,
                    )

            if final_channel_id != INVALID_CHANNEL_ID:
                self.services.logger.info(
                    "[%s] Attempting to join channel: '%s' (Resolved ID: %s).",
                    connection.server_info.host,
                    target_channel_name_log,
                    final_channel_id,
                )
                tt_instance.join_channel_by_id(final_channel_id, password=channel_password)
            else:
                self.services.logger.warning(
                    "[%s] Could not resolve channel '%s'. Bot remains in default channel.",
                    connection.server_info.host,
                    channel_id_or_path,
                )
                current_bot_channel_id = tt_instance.getMyCurrentChannelID()
                if current_bot_channel_id == final_channel_id or (
                    final_channel_id == INVALID_CHANNEL_ID and current_bot_channel_id is not None
                ):
                    self.services.logger.info(
                        "[%s] Bot already in a channel or no specific channel join needed. Attempting to finalize.",
                        connection.server_info.host,
                    )
                    current_channel_obj = tt_instance.get_channel(current_bot_channel_id)
                    if current_channel_obj:
                        await self._finalize_bot_login_sequence(connection, current_channel_obj)
                    else:
                        self.services.logger.error(
                            "[%s] Bot in channel ID %s, but channel object not found.",
                            connection.server_info.host,
                            current_bot_channel_id,
                        )
        except PytalkPermissionError as e_perm_join:
            self.services.logger.error(
                "[%s] Pytalk PermissionError joining channel '%s': %s.",
                connection.server_info.host,
                target_channel_name_log,
                e_perm_join,
            )
        except ValueError as e_val_join:
            self.services.logger.exception(
                "[%s] ValueError joining channel '%s': %s.",
                connection.server_info.host,
                target_channel_name_log,
                e_val_join,
            )
        except TimeoutError as e_timeout_join:
            self.services.logger.exception(
                "[%s] TimeoutError during channel operations for '%s': %s.",
                connection.server_info.host,
                target_channel_name_log,
                e_timeout_join,
            )
            await self._initiate_reconnect_for_connection(connection)
        except TeamTalkException as e_pytalk_join:
            self.services.logger.exception(
                "[%s] Pytalk specific error joining channel '%s': %s.",
                connection.server_info.host,
                target_channel_name_log,
                e_pytalk_join,
            )
            await self._initiate_reconnect_for_connection(connection)
        except Exception as e:
            self.services.logger.exception(
                "[%s] Unexpected error during channel join logic: %s", connection.server_info.host, e
            )
            await self._initiate_reconnect_for_connection(connection)

    async def on_pytalk_user_join(self, user: PytalkUser, channel: PytalkChannel):
        """Handles the Pytalk `on_user_join` event.

        This is called when any user (including the bot itself) joins a channel.
        If it's the bot joining, it finalizes the login sequence.
        """
        tt_instance = getattr(user.server, "teamtalk_instance", None) or getattr(user, "teamtalk_instance", None)
        if not tt_instance:
            self.services.logger.error(
                "CRITICAL: Could not retrieve TeamTalk instance in on_pytalk_user_join "
                "for user %s. Cannot process event.",
                pytalk.instance.sdk.ttstr(user.username),
            )
            return

        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error("on_pytalk_user_join: Received event for instance not managed: %s", tt_instance)
            return

        connection.update_caches_on_event("user_join", user)
        my_user_id = tt_instance.getMyUserID()
        if my_user_id is None:
            self.services.logger.error(
                "[%s] CRITICAL: Failed to get bot's own user ID in on_user_join.", connection.server_info.host
            )
            return

        if user.id == my_user_id:
            if not connection.is_finalized:
                await self._finalize_bot_login_sequence(connection, channel)
            else:
                self.services.logger.info(
                    "[%s] Bot re-joined channel %s, already finalized.",
                    connection.server_info.host,
                    pytalk.instance.sdk.ttstr(channel.name),
                )

    async def on_pytalk_my_connection_lost(self, server: PytalkServer):
        """Handles the Pytalk `on_my_connection_lost` event.

        This is called when the bot loses connection to a server it was logged into.
        It initiates a reconnection sequence.
        """
        tt_instance = server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error(
                "on_pytalk_my_connection_lost: Received event for unknown instance: %s. Server host from event: %s",
                tt_instance,
                server.info.host if server and server.info else "Unknown",
            )
            if server and server.info:
                connection = self._get_connection_by_server_info(server.info)
                if not connection:
                    self.services.logger.error(
                        "Still could not find connection for lost server %s:%s",
                        server.info.host,
                        server.info.tcp_port,
                    )
                    return
                else:
                    self.services.logger.warning(
                        "Found connection for %s via server_info after instance lookup failed for connection_lost.",
                        server.info.host,
                    )
            else:
                return

        server_host_display = connection.server_info.host if connection else "Unknown Server"
        self.services.logger.warning(
            "[%s] Connection lost to server. Initiating reconnection process...", server_host_display
        )
        connection.mark_finalized(False)
        connection.login_complete_time = None
        await connection.stop_background_tasks()
        await self._initiate_reconnect_for_connection(connection)

    async def on_pytalk_my_kicked_from_channel(self, channel_obj: PytalkChannel):
        """Handles the Pytalk `on_my_kicked_from_channel` event.

        This is called when the bot is kicked from a channel.
        It initiates a full reconnection sequence for that server connection.
        """
        tt_instance = channel_obj.teamtalk
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error(
                "on_pytalk_my_kicked_from_channel: Received event for unknown instance: %s", tt_instance
            )
            return

        channel_name = (
            pytalk.instance.sdk.ttstr(channel_obj.name) if channel_obj and channel_obj.name else "Unknown Channel"
        )
        self.services.logger.warning(
            "[%s] Kicked from channel '%s'. Initiating full reconnection for this connection...",
            connection.server_info.host,
            channel_name,
        )
        connection.mark_finalized(False)
        connection.login_complete_time = None
        await connection.stop_background_tasks()
        await self._initiate_reconnect_for_connection(connection)

    async def on_pytalk_message(self, message: TeamTalkMessage):
        """Handles incoming TeamTalk messages.

        Processes commands or forwards private messages to the Telegram admin.
        """
        tt_instance = message.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection or not connection.instance:
            self.services.logger.error(
                "on_pytalk_message: Received message for unknown or uninitialized instance. Message from: %s",
                message.from_id,
            )
            return

        if message.from_id == connection.instance.getMyUserID() or message.type != TEAMTALK_PRIVATE_MESSAGE_TYPE:
            return

        sender_username = pytalk.instance.sdk.ttstr(message.user.username)
        message_content = message.content.strip()
        self.services.logger.debug(
            "[%s] Received private TT message from %s: '%s...'.",
            connection.server_info.host,
            sender_username,
            message_content[:100],
        )

        bot_reply_language_code = self.services.config.general.default_lang
        admin_chat_id_for_message = self.services.config.telegram.admin_chat_id
        if admin_chat_id_for_message:
            admin_settings = self.services.user_settings_cache.get(admin_chat_id_for_message)
            if admin_settings and admin_settings.language_code:
                bot_reply_language_code = admin_settings.language_code

        translator = self.services.get_translator(bot_reply_language_code)
        _ = translator.gettext

        command_parts = message_content.split(maxsplit=1)
        command_name = command_parts[0].lower()
        tt_command_handlers = {
            "/sub": handle_tt_subscribe_command,
            "/unsub": handle_tt_unsubscribe_command,
            "/add_admin": handle_tt_add_admin_command,
            "/remove_admin": handle_tt_remove_admin_command,
            "/help": handle_tt_help_command,
        }
        handler = tt_command_handlers.get(command_name)

        async with self.services.session_factory() as session:
            if handler:
                args_str = command_parts[1] if len(command_parts) > 1 else None
                if command_name in ["/add_admin", "/remove_admin"]:
                    await handler(
                        message,
                        args_str=args_str,
                        session=session,
                        translator=translator,
                        services=self.services,
                        connection=connection,
                    )
                elif command_name == "/help":
                    await handler(message, translator=translator, services=self.services, connection=connection)
                else:
                    await handler(
                        message, session=session, translator=translator, services=self.services, connection=connection
                    )
            elif message_content.startswith("/"):
                await handle_tt_unknown_command(message, translator, connection=connection)  # Pass translator
            else:
                await forward_tt_message_to_telegram_admin(
                    message=message,
                    services=self.services,
                    server_host_for_display=connection.server_info.host,
                    translator=translator,  # Pass translator
                )

    async def on_pytalk_user_login(self, user: PytalkUser):
        """Handles the Pytalk `on_user_login` event (other users logging in).

        Updates caches and triggers join notification logic.
        """
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            return
        connection.update_caches_on_event("user_login", user)
        await send_join_leave_notification_logic(
            services=self.services,
            event_type=NOTIFICATION_EVENT_JOIN,
            tt_user=user,
            tt_instance=connection.instance,
            login_complete_time=connection.login_complete_time,
            online_users_cache_for_instance=connection.online_users_cache,
        )

    async def on_pytalk_user_logout(self, user: PytalkUser):
        """Handles the Pytalk `on_user_logout` event (other users logging out).

        Updates caches and triggers leave notification logic.
        """
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            return
        connection.update_caches_on_event("user_logout", user)
        await send_join_leave_notification_logic(
            services=self.services,
            event_type=NOTIFICATION_EVENT_LEAVE,
            tt_user=user,
            tt_instance=connection.instance,
            login_complete_time=connection.login_complete_time,
            online_users_cache_for_instance=connection.online_users_cache,
        )

    async def on_pytalk_user_update(self, user: PytalkUser):
        """Handles the Pytalk `on_user_update` event.

        Updates the online user cache with the changed user information.
        """
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            return
        connection.update_caches_on_event("user_update", user)

    async def on_pytalk_user_account_new(self, account: pytalk.UserAccount):
        """Handles the Pytalk `on_user_account_new` event.

        Updates the user accounts cache for the relevant connection(s).
        """
        tt_instance = getattr(account, "teamtalk_instance", None)
        if not tt_instance:
            self.services.logger.warning(
                "on_pytalk_user_account_new: No teamtalk_instance found on account object. "
                "Cannot route event. Account: %s",
                account.username,
            )
            for conn_val in self.services.connections.values():
                conn_val.update_caches_on_event("user_account_new", account)
            return
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error(
                "on_pytalk_user_account_new: Received event for instance not managed: %s", tt_instance
            )
            return
        connection.update_caches_on_event("user_account_new", account)

    async def on_pytalk_user_account_remove(self, account: pytalk.UserAccount):
        """Handles the Pytalk `on_user_account_remove` event.

        Updates the user accounts cache for the relevant connection(s).
        """
        tt_instance = getattr(account, "teamtalk_instance", None)
        if not tt_instance:
            self.services.logger.warning(
                "on_pytalk_user_account_remove: No teamtalk_instance found on account object. "
                "Cannot route event. Account: %s",
                account.username,
            )
            for conn_val in self.services.connections.values():
                conn_val.update_caches_on_event("user_account_remove", account)
            return
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error(
                "on_pytalk_user_account_remove: Received event for instance not managed: %s", tt_instance
            )
            return
        connection.update_caches_on_event("user_account_remove", account)
