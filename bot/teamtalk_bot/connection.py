"""Manages a single connection to a TeamTalk server, including state and caches."""

import asyncio
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.enums import Status as PytalkStatus
from pytalk.enums import TeamTalkServerInfo as PytalkTeamTalkServerInfo
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser
from pytalk.user_account import UserAccount as PytalkUserAccount

from bot.constants import (
    INVALID_CHANNEL_ID,
    NOTIFICATION_EVENT_JOIN,
    NOTIFICATION_EVENT_LEAVE,
    TEAMTALK_PRIVATE_MESSAGE_TYPE,
)
from bot.core.notifications import send_join_leave_notification_logic
from bot.teamtalk_bot import command_constants as tt_cmds  # Import constants
from bot.teamtalk_bot.commands import (
    handle_tt_add_admin_command,
    handle_tt_help_command,
    handle_tt_remove_admin_command,
    handle_tt_subscribe_command,
    handle_tt_unknown_command,
    handle_tt_unsubscribe_command,
)
from bot.teamtalk_bot.utils import (
    forward_tt_message_to_telegram_admin,
)

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)


class TeamTalkConnection:
    """Manages the state of a single connection to a TeamTalk server."""

    def __init__(
        self,
        server_info: PytalkTeamTalkServerInfo,
        pytalk_bot: pytalk.TeamTalkBot,
        services: "Services",
    ):
        """Initializes a TeamTalkConnection instance."""
        self.server_info = server_info
        self.pytalk_bot = pytalk_bot
        self.services = services
        self.instance: pytalk.instance.TeamTalkInstance | None = None
        self.login_complete_time: datetime | None = None
        self.online_users_cache: dict[int, PytalkUser] = {}
        self.user_accounts_cache: dict[str, PytalkUserAccount] = {}
        self._periodic_sync_task: asyncio.Task[Any] | None = None
        self._populate_accounts_task: asyncio.Task[Any] | None = None
        self._is_finalized = False
        self.ttstr = pytalk.instance.sdk.ttstr

    async def connect(self) -> bool:
        """Establishes a connection to the TeamTalk server."""
        logger.info("Adding server %s:%s to PytalkBot.", self.server_info.host, self.server_info.tcp_port)
        try:
            num_instances_before = len(self.pytalk_bot.teamtalks)
            await self.pytalk_bot.add_server(self.server_info)
            num_instances_after = len(self.pytalk_bot.teamtalks)
            if num_instances_after > num_instances_before:
                self.instance = self.pytalk_bot.teamtalks[-1]
                logger.info("Added server %s. Instance: %s", self.server_info.host, self.instance)
                self._is_finalized = False
                self.login_complete_time = None
                return True
            logger.error("Failed to add server %s: PytalkBot.teamtalks unchanged.", self.server_info.host)
            return False
        except Exception as e:
            logger.exception("Exception during add_server for %s: %s", self.server_info.host, e)
            return False

    async def _periodic_cache_sync(self) -> None:
        """Periodically synchronizes the online users cache with the server."""
        if not self.instance:
            logger.error("[%s] Sync: No instance.", self.server_info.host)
            return
        logger.info("[%s] Starting periodic online users cache sync.", self.server_info.host)
        cfg_params = self.services.config.operational_parameters
        sync_interval = cfg_params.online_users_cache_sync_interval_seconds
        reconnect_check_interval = cfg_params.tt_reconnect_check_interval_seconds
        reconnect_retry_interval = cfg_params.tt_reconnect_retry_seconds
        while True:
            try:
                if self.is_ready:
                    logger.debug("[%s] Syncing online users...", self.server_info.host)
                    server_users = self.instance.server.get_users()
                    new_cache = {user.id: user for user in server_users if hasattr(user, "id")}
                    self.online_users_cache.clear()
                    self.online_users_cache.update(new_cache)
                    logger.debug(
                        "[%s] Online users cache synced: %s users.",
                        self.server_info.host, len(self.online_users_cache)
                    )
                else:
                    logger.warning("[%s] Sync: TT instance not ready.", self.server_info.host)
                    await asyncio.sleep(reconnect_check_interval)
                    continue
            except TimeoutError as e_timeout:
                logger.exception(
                    "[%s] Timeout in periodic sync: %s", self.server_info.host, e_timeout
                )
                await asyncio.sleep(sync_interval // 2)
            except pytalk.exceptions.TeamTalkException as e_pytalk:
                logger.exception(
                    "[%s] Pytalk error in periodic sync: %s", self.server_info.host, e_pytalk
                )
                await asyncio.sleep(reconnect_retry_interval if self.is_ready else reconnect_check_interval)
            except Exception as e:
                logger.exception(
                    "[%s] Unexpected error in periodic sync: %s", self.server_info.host, e
                )
                await asyncio.sleep(sync_interval)
            await asyncio.sleep(sync_interval)

    async def populate_user_accounts_cache(self) -> None:
        """Populates the cache of user accounts from the TeamTalk server."""
        if not self.is_ready:
            logger.warning("[%s] Populate accounts: instance not ready.", self.server_info.host)
            return
        logger.info("[%s] Populating user accounts cache...", self.server_info.host)
        try:
            if self.instance:
                all_accounts = await self.instance.list_user_accounts()
                if all_accounts:
                    self.user_accounts_cache.clear()
                    for acc in all_accounts:
                        username_str = (
                            self.ttstr(acc.username)
                            if isinstance(acc.username, bytes)
                            else str(acc.username)
                        )
                        if username_str:
                            self.user_accounts_cache[username_str] = acc
                logger.info(
                    "[%s] Accounts cache populated: %s accounts.",
                    self.server_info.host, len(self.user_accounts_cache)
                )
        except TimeoutError as e_timeout:
            logger.exception("[%s] Timeout populating accounts: %s", self.server_info.host, e_timeout)
        except pytalk.exceptions.PermissionError as e_perm:
            logger.exception("[%s] PermissionError populating accounts: %s", self.server_info.host, e_perm)
        except pytalk.exceptions.TeamTalkException as e_pytalk:
            logger.exception("[%s] Pytalk error populating accounts: %s", self.server_info.host, e_pytalk)
        except Exception as e:
            logger.exception("[%s] Unexpected error populating accounts: %s", self.server_info.host, e)

    def start_background_tasks(self) -> None:
        """Starts background tasks for this connection (cache syncs)."""
        if not self.instance:
            logger.error("[%s] Start tasks: No instance.", self.server_info.host)
            return
        if self._periodic_sync_task is None or self._periodic_sync_task.done():
            self._periodic_sync_task = asyncio.create_task(self._periodic_cache_sync())
            logger.info("[%s] Online users sync task started.", self.server_info.host)
        if self._populate_accounts_task is None or self._populate_accounts_task.done():
            self._populate_accounts_task = asyncio.create_task(self.populate_user_accounts_cache())
            logger.info("[%s] Accounts cache task started.", self.server_info.host)

    async def stop_background_tasks(self) -> None:
        """Stops all running background tasks for this connection."""
        logger.info("[%s] Stopping background tasks...", self.server_info.host)
        tasks_to_stop = {
            "_periodic_sync_task": self._periodic_sync_task,
            "_populate_accounts_task": self._populate_accounts_task,
        }
        for name, task in tasks_to_stop.items():
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info("[%s] Task %s cancelled.", self.server_info.host, name)
                except Exception as e:
                    logger.exception("[%s] Error stopping task %s: %s", self.server_info.host, name, e)
            setattr(self, name, None)
        logger.info("[%s] Background tasks stopped.", self.server_info.host)

    async def disconnect_instance(self) -> None:
        """Disconnects the TeamTalk instance and cleans up resources."""
        await self.stop_background_tasks()
        if self.instance:
            logger.info("[%s] Disconnecting instance...", self.server_info.host)
            try:
                if self.instance.logged_in:
                    self.instance.logout()
                if self.instance.connected:
                    self.instance.disconnect()
                logger.info("[%s] Instance disconnected.", self.server_info.host)
            except Exception as e:
                logger.exception("[%s] Error during instance disconnect: %s", self.server_info.host, e)
        self._is_finalized = False
        self.login_complete_time = None

    @property
    def is_ready(self) -> bool:
        """Checks if instance is connected and logged in."""
        return self.instance is not None and self.instance.connected and self.instance.logged_in

    @property
    def is_finalized(self) -> bool:
        """Checks if login sequence has been finalized."""
        return self._is_finalized

    def mark_finalized(self, status: bool = True) -> None:
        """Marks the login sequence as finalized or not."""
        self._is_finalized = status
        logger.info("[%s] Connection marked: %s.", self.server_info.host, "finalized" if status else "NOT finalized")

    def update_caches_on_event(self, event_type: str, data: Any) -> None:
        """Updates internal caches based on TeamTalk user or account events."""
        user_id = getattr(data, "id", None)
        username_attr = getattr(data, "username", None)
        username_str = self.ttstr(username_attr) if username_attr else "UnknownUser"

        if event_type in ["user_login", "user_join", "user_update"]:
            user_data: PytalkUser = data
            if user_id is not None:
                self.online_users_cache[user_id] = user_data
                logger.debug(
                    "[%s] User %s (%s) %s -> online_users_cache (%s).",
                    self.server_info.host, user_id, username_str, event_type, len(self.online_users_cache)
                )
        elif event_type == "user_logout":
            if user_id is not None and user_id in self.online_users_cache:
                del self.online_users_cache[user_id]
                logger.debug(
                    "[%s] User %s (%s) logged out. Cache size: %s.",
                    self.server_info.host, user_id, username_str, len(self.online_users_cache)
                )
        elif event_type == "user_account_new":
            acc: PytalkUserAccount = data
            acc_username = self.ttstr(acc.username) if acc.username else ""
            if acc_username:
                self.user_accounts_cache[acc_username] = acc
            logger.debug(
                "[%s] Account '%s' added. Cache size: %s.",
                self.server_info.host, acc_username, len(self.user_accounts_cache)
            )
        elif event_type == "user_account_remove":
            acc: PytalkUserAccount = data
            acc_username = self.ttstr(acc.username) if acc.username else ""
            if acc_username and acc_username in self.user_accounts_cache:
                del self.user_accounts_cache[acc_username]
            logger.debug(
                "[%s] Account '%s' removed. Cache size: %s.",
                self.server_info.host, acc_username, len(self.user_accounts_cache)
            )

    async def _finalize_bot_login_sequence(self, channel: PytalkChannel):
        """Finalizes the bot's login sequence for this connection."""
        if self.is_finalized:
            logger.info("[%s] Login sequence already finalized. Skipping.", self.server_info.host)
            return
        if not self.instance:
            logger.error("[%s] No instance to finalize login.", self.server_info.host)
            return

        ch_name = self.ttstr(channel.name) if hasattr(channel, "name") and channel.name else "Unknown"
        logger.info(
            "[%s] Bot in channel: %s. Finalizing login...", self.server_info.host, ch_name
        )

        logger.info("[%s] Initial online users cache population...", self.server_info.host)
        try:
            users = self.instance.server.get_users()
            self.online_users_cache.clear()
            for u in users:
                if hasattr(u, "id"):
                    self.online_users_cache[u.id] = u
            logger.info(
                "[%s] Online users cache init: %s users.",
                self.server_info.host, len(self.online_users_cache)
            )
        except Exception as e:
            logger.exception("[%s] Error initial online users cache: %s", self.server_info.host, e)

        self.start_background_tasks()
        try:
            gender = self.services.config.general.gender.lower()
            status_val = PytalkStatus.online.neutral
            if gender == "male":
                status_val = PytalkStatus.online.male
            elif gender == "female":
                status_val = PytalkStatus.online.female

            status_text = self.services.config.teamtalk.status_text
            self.instance.change_status(status_val, status_text)
            self.login_complete_time = datetime.utcnow()
            self.mark_finalized(True)
            logger.info(
                "[%s] Login finalized at %s. Status: '%s'",
                self.server_info.host, self.login_complete_time, status_text
            )
        except Exception as e:
            logger.exception("[%s] Error finalizing login (status/time): %s", self.server_info.host, e)

    async def _initiate_reconnect(self):
        """Initiates a reconnection sequence for this connection."""
        server_key = f"{self.server_info.host}:{self.server_info.tcp_port}"
        logger.info("[%s] Initiating reconnect.", server_key)
        await self.disconnect_instance()
        logger.info("[%s] Attempting re-connect.", server_key)
        if await self.connect():
            logger.info("[%s] Reconnect initiated. Waiting for login.", server_key)
        else:
            logger.error("[%s] Failed to re-initiate connection.", server_key)

    async def _determine_target_channel(self) -> tuple[int, str]:
        """Determines the target channel ID and name from config."""
        if not self.instance:
            return INVALID_CHANNEL_ID, ""

        cfg_tt = self.services.config.teamtalk
        chan_path = cfg_tt.channel
        target_chan_name = chan_path
        final_chan_id = INVALID_CHANNEL_ID

        if chan_path.isdigit():
            final_chan_id = int(chan_path)
            ch_obj = self.instance.get_channel(final_chan_id)
            if ch_obj:
                target_chan_name = self.ttstr(ch_obj.name)
            else: # Channel ID specified but not found
                logger.warning("[%s] Channel ID '%s' not found.", self.server_info.host, chan_path)
                final_chan_id = INVALID_CHANNEL_ID # Reset if not found
        else:
            ch_obj = self.instance.get_channel_from_path(chan_path)
            if ch_obj:
                final_chan_id = ch_obj.id
                target_chan_name = self.ttstr(ch_obj.name)
            else:
                logger.error("[%s] Channel path '%s' not found.", self.server_info.host, chan_path)
        return final_chan_id, target_chan_name

    async def _join_configured_channel(self) -> None:
        """Joins the configured TeamTalk channel."""
        if not self.instance:
            logger.error("[%s] No instance to join channel.", self.server_info.host)
            await self._initiate_reconnect()
            return

        final_chan_id, target_chan_name = await self._determine_target_channel()
        chan_pass = self.services.config.teamtalk.channel_password or ""

        try:
            if final_chan_id != INVALID_CHANNEL_ID:
                logger.info(
                    "[%s] Joining chan: '%s' (ID: %s).",
                    self.server_info.host, target_chan_name, final_chan_id
                )
                self.instance.join_channel_by_id(final_chan_id, password=chan_pass)
            else:
                logger.warning(
                    "[%s] No valid target channel found/configured. Staying in default channel.", self.server_info.host
                )
                # If not joining a specific channel, finalize with the current one.
                curr_chan_id = self.instance.getMyCurrentChannelID()
                ch_to_finalize = self.instance.get_channel(curr_chan_id if curr_chan_id is not None else 0)
                if ch_to_finalize:
                    await self._finalize_bot_login_sequence(ch_to_finalize)
                else:
                    logger.warning("[%s] Could not get current/root channel to finalize.", self.server_info.host)

        except pytalk.exceptions.PermissionError as e_perm:
            logger.error(
                "[%s] PermissionError joining '%s': %s. Will try to finalize in current/default channel.",
                self.server_info.host, target_chan_name, e_perm
            )
            # Attempt to finalize in the current channel if join failed due to permissions
            curr_chan_id_after_fail = self.instance.getMyCurrentChannelID()
            ch_id_to_get = curr_chan_id_after_fail if curr_chan_id_after_fail is not None else 0
            ch_to_finalize_after_fail = self.instance.get_channel(ch_id_to_get)
            if ch_to_finalize_after_fail:
                await self._finalize_bot_login_sequence(ch_to_finalize_after_fail)
            else:
                logger.error(
                    "[%s] Could not get current channel (ID: %s) to finalize after permission error.",
                    self.server_info.host, ch_id_to_get
                )

        except Exception as e:
            logger.exception("[%s] Error during channel join/finalization: %s", self.server_info.host, e)
            await self._initiate_reconnect()


    async def on_my_login(self, server: PytalkServer):
        """Handles the bot's own login event for this connection."""
        self.login_complete_time = None
        self.mark_finalized(False)
        server_name_display = "Unknown Server"

        if self.instance:
            try:
                props = self.instance.server.get_properties()
                if props:
                    server_name_display = self.ttstr(props.server_name)
            except Exception as e:
                logger.warning("[%s] Error getting server props: %s", self.server_info.host, e)
        else: # Should ideally not happen if connect() succeeded
            logger.error("[%s] No instance available at start of on_my_login.", self.server_info.host)
            await self._initiate_reconnect() # Attempt to recover
            return

        logger.info(
            "[%s] Logged in to TT: %s. Instance: %s",
            self.server_info.host, server_name_display, self.instance
        )
        await self._join_configured_channel()


    async def on_user_join(self, user: PytalkUser, channel: PytalkChannel):
        """Handles another user joining a channel on this server connection."""
        self.update_caches_on_event("user_join", user)
        if not self.instance:
            logger.error("[%s] No instance in on_user_join.", self.server_info.host)
            return
        my_user_id = self.instance.getMyUserID()
        if my_user_id is None:
            logger.error("[%s] Failed to get bot's ID in on_user_join.", self.server_info.host)
            return
        if user.id == my_user_id:
            if not self.is_finalized:
                await self._finalize_bot_login_sequence(channel)
            else:
                logger.info(
                    "[%s] Bot re-joined chan %s (finalized).",
                    self.server_info.host, self.ttstr(channel.name)
                )

    async def on_my_connection_lost(self, server: PytalkServer):
        """Handles disconnection from the server for this connection."""
        logger.warning("[%s] Connection lost. Reconnecting...", self.server_info.host)
        self.mark_finalized(False)
        self.login_complete_time = None
        await self.stop_background_tasks()
        await self._initiate_reconnect()

    async def on_my_kicked_from_channel(self, channel_obj: PytalkChannel):
        """Handles being kicked from a channel on this server connection."""
        ch_name = self.ttstr(channel_obj.name) if channel_obj and channel_obj.name else "Unknown"
        logger.warning("[%s] Kicked from chan '%s'. Reconnecting...", self.server_info.host, ch_name)
        self.mark_finalized(False)
        self.login_complete_time = None
        await self.stop_background_tasks()
        await self._initiate_reconnect()

    async def on_message(self, message: TeamTalkMessage):
        """Handles an incoming message on this server connection."""
        if not self.instance or message.from_id == self.instance.getMyUserID() or \
           message.type != TEAMTALK_PRIVATE_MESSAGE_TYPE:
            return

        sender = self.ttstr(message.user.username)
        content = message.content.strip()
        logger.debug("[%s] Private msg from %s: '%s'", self.server_info.host, sender, content[:50])

        admin_cfg = self.services.config.telegram.admin_chat_id
        reply_lang = self.services.config.general.default_lang
        if admin_cfg:
            admin_settings = self.services.cache.get_user_settings(admin_cfg)
            if admin_settings and admin_settings.language_code:
                reply_lang = admin_settings.language_code
        translator = self.services.get_translator(reply_lang)

        parts = content.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else None

        handlers = {
            tt_cmds.TT_CMD_SUBSCRIBE: handle_tt_subscribe_command,
            tt_cmds.TT_CMD_UNSUBSCRIBE: handle_tt_unsubscribe_command,
            tt_cmds.TT_CMD_ADD_ADMIN: handle_tt_add_admin_command,
            tt_cmds.TT_CMD_REMOVE_ADMIN: handle_tt_remove_admin_command,
            tt_cmds.TT_CMD_HELP: handle_tt_help_command,
        }
        handler = handlers.get(cmd)

        async with self.services.session_factory() as session:
            if handler:
                kwargs = {
                    "tt_message": message, "translator": translator,
                    "services": self.services, "connection": self
                }
                if cmd in [tt_cmds.TT_CMD_ADD_ADMIN, tt_cmds.TT_CMD_REMOVE_ADMIN]:
                    kwargs["args_str"] = args
                # All current commands in handlers dict require session except /help
                if cmd != tt_cmds.TT_CMD_HELP:
                    kwargs["session"] = session
                await handler(**kwargs)
            elif content.startswith("/"): # Check if it's an attempt at a command
                await handle_tt_unknown_command(message, translator, connection=self)
            else: # Not a command, forward as message
                await forward_tt_message_to_telegram_admin(
                    message=message, services=self.services,
                    server_host_for_display=self.server_info.host, translator=translator
                )

    async def on_user_login(self, user: PytalkUser):
        """Handles another user logging into this server connection."""
        self.update_caches_on_event("user_login", user)
        if not self.instance:
            return
        await send_join_leave_notification_logic(
            services=self.services, event_type=NOTIFICATION_EVENT_JOIN,
            tt_user=user, tt_instance=self.instance,
            login_complete_time=self.login_complete_time,
            online_users_cache_for_instance=self.online_users_cache,
        )

    async def on_user_logout(self, user: PytalkUser):
        """Handles another user logging out from this server connection."""
        self.update_caches_on_event("user_logout", user)
        if not self.instance:
            return
        await send_join_leave_notification_logic(
            services=self.services, event_type=NOTIFICATION_EVENT_LEAVE,
            tt_user=user, tt_instance=self.instance,
            login_complete_time=self.login_complete_time,
            online_users_cache_for_instance=self.online_users_cache,
        )

    async def on_user_update(self, user: PytalkUser):
        """Handles updates to a user's information on this server connection."""
        self.update_caches_on_event("user_update", user)

    async def on_user_account_new(self, account: pytalk.UserAccount):
        """Handles a new user account being created on this server."""
        self.update_caches_on_event("user_account_new", account)

    async def on_user_account_remove(self, account: pytalk.UserAccount):
        """Handles a user account being removed from this server."""
        self.update_caches_on_event("user_account_remove", account)

    def __repr__(self) -> str:
        """Returns a string representation of the TeamTalkConnection object."""
        instance_id = id(self.instance) if self.instance else "N/A"
        return (f"<TeamTalkConnection host={self.server_info.host}:{self.server_info.tcp_port} "
                f"instance_id={instance_id} finalized={self.is_finalized}>")
