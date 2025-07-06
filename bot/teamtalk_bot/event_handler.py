import logging
from datetime import datetime
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
    def __init__(self, services: "Services"):
        self.services = services
        self.tt_bot = services.tt_bot
        self._register_pytalk_event_handlers()
        self.services.logger.info("TeamTalkEventHandler initialized and Pytalk event handlers registered.")

    def _register_pytalk_event_handlers(self):
        event_handlers_map = {
            'on_ready': self.on_pytalk_ready,
            'on_my_login': self.on_pytalk_my_login,
            'on_my_connection_lost': self.on_pytalk_my_connection_lost,
            'on_my_kicked_from_channel': self.on_pytalk_my_kicked_from_channel,
            'on_message': self.on_pytalk_message,
            'on_user_login': self.on_pytalk_user_login,
            'on_user_join': self.on_pytalk_user_join,
            'on_user_logout': self.on_pytalk_user_logout,
            'on_user_update': self.on_pytalk_user_update,
            'on_user_account_new': self.on_pytalk_user_account_new,
            'on_user_account_remove': self.on_pytalk_user_account_remove,
        }
        for event_name, handler_method in event_handlers_map.items():
            setattr(self.tt_bot, event_name, self.tt_bot.event(handler_method))

    def _get_connection_by_instance(
        self, tt_instance: pytalk.instance.TeamTalkInstance
    ) -> TeamTalkConnection | None:
        for conn in self.services.connections.values():
            if conn.instance is tt_instance:
                return conn
        self.services.logger.warning(
            f"Could not find an active TeamTalkConnection for instance: {tt_instance}"
        )
        return None

    def _get_connection_by_server_info(
        self, server_info: pytalk.TeamTalkServerInfo
    ) -> TeamTalkConnection | None:
        server_key = f"{server_info.host}:{server_info.tcp_port}"
        return self.services.connections.get(server_key)

    async def _finalize_bot_login_sequence(self, connection: TeamTalkConnection, channel: PytalkChannel):
        if connection.is_finalized:
            self.services.logger.info(
                f"[{connection.server_info.host}] Login sequence already finalized. Skipping."
            )
            return

        if not connection.instance:
            self.services.logger.error(
                f"[{connection.server_info.host}] Cannot finalize login sequence: "
                f"instance not available in connection object."
            )
            return

        tt_instance = connection.instance
        if hasattr(channel, "name") and isinstance(channel.name, bytes):
            channel_name_display = pytalk.instance.sdk.ttstr(channel.name)
        else:
            channel_name_display = str(channel.name)
        self.services.logger.info(
            f"[{connection.server_info.host}] Bot successfully joined channel: {channel_name_display}. "
            f"Finalizing login sequence..."
        )

        self.services.logger.info(
            f"[{connection.server_info.host}] Performing initial population of online users cache..."
        )
        try:
            initial_online_users = tt_instance.server.get_users()
            connection.online_users_cache.clear()
            for u in initial_online_users:
                if hasattr(u, "id"):
                    connection.online_users_cache[u.id] = u
            self.services.logger.info(
                f"[{connection.server_info.host}] Online users cache initialized with "
                f"{len(connection.online_users_cache)} users."
            )
        except Exception as e:
            self.services.logger.error(
                f"[{connection.server_info.host}] Error during initial online users cache population: {e}",
                exc_info=True
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
                f"[{connection.server_info.host}] TeamTalk status set to: "
                f"'{self.services.config.teamtalk.status_text}'."
            )
            self.services.logger.info(
                f"[{connection.server_info.host}] TeamTalk login sequence finalized at "
                f"{connection.login_complete_time}."
            )
        except Exception as e:
            self.services.logger.error(
                f"[{connection.server_info.host}] Error setting status or "
                f"login_complete_time for bot: {e}", exc_info=True
            )

    async def _initiate_reconnect_for_connection(self, connection: TeamTalkConnection):
        if not connection:
            self.services.logger.error("Reconnect requested for a null connection object.")
            return

        server_key = f"{connection.server_info.host}:{connection.server_info.tcp_port}"
        self.services.logger.info(f"[{server_key}] Starting reconnection logic.")

        await connection.disconnect_instance()

        self.services.logger.info(f"[{server_key}] Attempting to re-establish connection...")
        if await connection.connect():
            self.services.logger.info(
                f"[{server_key}] Reconnect attempt initiated. Waiting for login events."
            )
        else:
            self.services.logger.error(
                f"[{server_key}] Failed to re-initiate connection via connection.connect()."
            )

    async def on_pytalk_ready(self):
        self.services.logger.info(
            "TeamTalkEventHandler: Pytalk Bot is ready. Initializing TeamTalk connections..."
        )
        tt_config = self.services.config.teamtalk
        pytalk_server_info = pytalk.TeamTalkServerInfo(
            host=tt_config.host_name,
            tcp_port=tt_config.port,
            udp_port=tt_config.port,
            username=tt_config.user_name,
            password=tt_config.password,
            encrypted=tt_config.encrypted,
            nickname=tt_config.nick_name,
            join_channel_id=int(tt_config.channel) if tt_config.channel.isdigit() else -1,
            join_channel_password=tt_config.channel_password or ""
        )
        server_key = f"{pytalk_server_info.host}:{pytalk_server_info.tcp_port}"

        if server_key in self.services.connections:
            self.services.logger.warning(
                f"Connection for {server_key} already exists. Reconnecting."
            )
            await self.services.connections[server_key].disconnect_instance()

        connection = TeamTalkConnection(
            server_info=pytalk_server_info,
            pytalk_bot=self.tt_bot,
            session_factory=self.services.session_factory,
            app_config=self.services.config
        )
        self.services.connections[server_key] = connection

        self.services.logger.info(f"Attempting to connect TeamTalkConnection for {server_key}...")
        if not await connection.connect():
            self.services.logger.error(
                f"Failed to initiate connection for {server_key} via TeamTalkConnection.connect()."
            )
        else:
            self.services.logger.info(
                f"TeamTalkConnection for {server_key} initiated. Waiting for login events."
            )

    async def on_pytalk_my_login(self, server: PytalkServer):
        tt_instance = server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)

        if not connection:
            self.services.logger.error(
                f"on_pytalk_my_login: Received login event for unknown instance: {tt_instance}. "
                f"Server: {server.info.host}"
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
                f"[{connection.server_info.host}] Error getting server properties on login: {e}"
            )

        self.services.logger.info(
            f"[{connection.server_info.host}] Successfully logged in to TeamTalk server: "
            f"{server_name_display} (Host: {server.info.host}). Current instance: {connection.instance}"
        )

        try:
            channel_id_or_path = self.services.config.teamtalk.channel
            channel_password = self.services.config.teamtalk.channel_password or ""
            target_channel_name_log = channel_id_or_path

            final_channel_id = -1
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
                        f"[{connection.server_info.host}] Channel path '{channel_id_or_path}' "
                        f"not found during login."
                    )

            if final_channel_id != -1:
                self.services.logger.info(
                    f"[{connection.server_info.host}] Attempting to join channel: "
                    f"'{target_channel_name_log}' (Resolved ID: {final_channel_id})."
                )
                tt_instance.join_channel_by_id(final_channel_id, password=channel_password)
            else:
                self.services.logger.warning(
                    f"[{connection.server_info.host}] Could not resolve channel '{channel_id_or_path}'. "
                    f"Bot remains in default channel."
                )
                current_bot_channel_id = tt_instance.getMyCurrentChannelID()
                if current_bot_channel_id == final_channel_id or \
                   (final_channel_id == -1 and current_bot_channel_id is not None):
                    self.services.logger.info(
                        f"[{connection.server_info.host}] Bot already in a channel or no specific "
                        f"channel join needed. Attempting to finalize."
                    )
                    current_channel_obj = tt_instance.get_channel(current_bot_channel_id)
                    if current_channel_obj:
                        await self._finalize_bot_login_sequence(connection, current_channel_obj)
                    else:
                        self.services.logger.error(
                            f"[{connection.server_info.host}] Bot in channel ID {current_bot_channel_id}, "
                            f"but channel object not found."
                        )
        except PytalkPermissionError as e_perm_join:
            self.services.logger.error(
                f"[{connection.server_info.host}] Pytalk PermissionError joining channel "
                f"'{target_channel_name_log}': {e_perm_join}.", exc_info=True
            )
        except ValueError as e_val_join:
            self.services.logger.error(
                f"[{connection.server_info.host}] ValueError joining channel "
                f"'{target_channel_name_log}': {e_val_join}.", exc_info=True
            )
        except TimeoutError as e_timeout_join:
            self.services.logger.error(
                f"[{connection.server_info.host}] TimeoutError during channel operations for "
                f"'{target_channel_name_log}': {e_timeout_join}.", exc_info=True
            )
            await self._initiate_reconnect_for_connection(connection)
        except TeamTalkException as e_pytalk_join:
            self.services.logger.error(
                f"[{connection.server_info.host}] Pytalk specific error joining channel "
                f"'{target_channel_name_log}': {e_pytalk_join}.", exc_info=True
            )
            await self._initiate_reconnect_for_connection(connection)
        except Exception as e:
            self.services.logger.error(
                f"[{connection.server_info.host}] Unexpected error during channel join logic: {e}",
                exc_info=True
            )
            await self._initiate_reconnect_for_connection(connection)

    async def on_pytalk_user_join(self, user: PytalkUser, channel: PytalkChannel):
        tt_instance = getattr(user.server, "teamtalk_instance", None) or \
                      getattr(user, "teamtalk_instance", None)
        if not tt_instance:
            self.services.logger.error(
                f"CRITICAL: Could not retrieve TeamTalk instance in on_pytalk_user_join for user "
                f"{pytalk.instance.sdk.ttstr(user.username)}. Cannot process event."
            )
            return

        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error(
                f"on_pytalk_user_join: Received event for instance not managed: {tt_instance}"
            )
            return

        connection.update_caches_on_event("user_join", user)
        my_user_id = tt_instance.getMyUserID()
        if my_user_id is None:
            self.services.logger.error(
                f"[{connection.server_info.host}] CRITICAL: Failed to get bot's own user ID "
                f"in on_user_join."
            )
            return

        if user.id == my_user_id:
            if not connection.is_finalized:
                await self._finalize_bot_login_sequence(connection, channel)
            else:
                self.services.logger.info(
                    f"[{connection.server_info.host}] Bot re-joined channel "
                    f"{pytalk.instance.sdk.ttstr(channel.name)}, already finalized."
                )

    async def on_pytalk_my_connection_lost(self, server: PytalkServer):
        tt_instance = server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error(
                f"on_pytalk_my_connection_lost: Received event for unknown instance: {tt_instance}. "
                f"Server host from event: {server.info.host if server and server.info else 'Unknown'}"
            )
            if server and server.info:
                connection = self._get_connection_by_server_info(server.info)
                if not connection:
                    self.services.logger.error(
                        f"Still could not find connection for lost server "
                        f"{server.info.host}:{server.info.tcp_port}"
                    )
                    return
                else:
                    self.services.logger.warning(
                        f"Found connection for {server.info.host} via server_info after "
                        f"instance lookup failed for connection_lost."
                    )
            else:
                return

        server_host_display = connection.server_info.host if connection else 'Unknown Server'
        self.services.logger.warning(
            f"[{server_host_display}] Connection lost to server. Initiating reconnection process..."
        )
        connection.mark_finalized(False)
        connection.login_complete_time = None
        await connection.stop_background_tasks()
        await self._initiate_reconnect_for_connection(connection)

    async def on_pytalk_my_kicked_from_channel(self, channel_obj: PytalkChannel):
        tt_instance = channel_obj.teamtalk
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error(
                f"on_pytalk_my_kicked_from_channel: Received event for unknown instance: {tt_instance}"
            )
            return

        channel_name = pytalk.instance.sdk.ttstr(channel_obj.name) if channel_obj and \
                       channel_obj.name else "Unknown Channel"
        self.services.logger.warning(
            f"[{connection.server_info.host}] Kicked from channel '{channel_name}'. "
            f"Initiating full reconnection for this connection..."
        )
        connection.mark_finalized(False)
        connection.login_complete_time = None
        await connection.stop_background_tasks()
        await self._initiate_reconnect_for_connection(connection)

    async def on_pytalk_message(self, message: TeamTalkMessage):
        tt_instance = message.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection or not connection.instance:
            self.services.logger.error(
                f"on_pytalk_message: Received message for unknown or uninitialized instance. "
                f"Message from: {message.from_id}"
            )
            return

        if (message.from_id == connection.instance.getMyUserID() or
                message.type != TEAMTALK_PRIVATE_MESSAGE_TYPE):
            return

        sender_username = pytalk.instance.sdk.ttstr(message.user.username)
        message_content = message.content.strip()
        self.services.logger.debug(
            f"[{connection.server_info.host}] Received private TT message from {sender_username}: "
            f"'{message_content[:100]}...'."
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
            "/sub": handle_tt_subscribe_command, "/unsub": handle_tt_unsubscribe_command,
            "/add_admin": handle_tt_add_admin_command, "/remove_admin": handle_tt_remove_admin_command,
            "/help": handle_tt_help_command,
        }
        handler = tt_command_handlers.get(command_name)

        async with self.services.session_factory() as session:
            if handler:
                args_str = command_parts[1] if len(command_parts) > 1 else None
                if command_name in ["/add_admin", "/remove_admin"]:
                    await handler(
                        message, args_str=args_str, session=session, translator=translator,
                        services=self.services, connection=connection
                    )
                elif command_name == "/help":
                    await handler(message, _=_, services=self.services, connection=connection)
                else:
                    await handler(message, session=session, _=_, services=self.services, connection=connection)
            elif message_content.startswith("/"):
                await handle_tt_unknown_command(message, _, connection=connection)
            else:
                await forward_tt_message_to_telegram_admin(
                    message=message, services=self.services,
                    server_host_for_display=connection.server_info.host
                )

    async def on_pytalk_user_login(self, user: PytalkUser):
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
            online_users_cache_for_instance=connection.online_users_cache
        )

    async def on_pytalk_user_logout(self, user: PytalkUser):
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
            online_users_cache_for_instance=connection.online_users_cache
        )

    async def on_pytalk_user_update(self, user: PytalkUser):
        tt_instance = user.server.teamtalk_instance
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            return
        connection.update_caches_on_event("user_update", user)

    async def on_pytalk_user_account_new(self, account: pytalk.UserAccount):
        tt_instance = getattr(account, 'teamtalk_instance', None)
        if not tt_instance:
            self.services.logger.warning(
                f"on_pytalk_user_account_new: No teamtalk_instance found on account object. "
                f"Cannot route event. Account: {account.username}"
            )
            for conn_val in self.services.connections.values():
                conn_val.update_caches_on_event("user_account_new", account)
            return
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error(
                f"on_pytalk_user_account_new: Received event for instance not managed: {tt_instance}"
            )
            return
        connection.update_caches_on_event("user_account_new", account)

    async def on_pytalk_user_account_remove(self, account: pytalk.UserAccount):
        tt_instance = getattr(account, 'teamtalk_instance', None)
        if not tt_instance:
            self.services.logger.warning(
                f"on_pytalk_user_account_remove: No teamtalk_instance found on account object. "
                f"Cannot route event. Account: {account.username}"
            )
            for conn_val in self.services.connections.values():
                conn_val.update_caches_on_event("user_account_remove", account)
            return
        connection = self._get_connection_by_instance(tt_instance)
        if not connection:
            self.services.logger.error(
                f"on_pytalk_user_account_remove: Received event for instance not managed: {tt_instance}"
            )
            return
        connection.update_caches_on_event("user_account_remove", account)
