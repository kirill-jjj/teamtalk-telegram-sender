"""Manages a single connection to a TeamTalk server, including state and caches."""

import asyncio
from datetime import datetime
import logging
from typing import Any  # For app_config_instance type hint and Optional

import pytalk
from pytalk.enums import TeamTalkServerInfo as PytalkTeamTalkServerInfo

logger = logging.getLogger(__name__)


class TeamTalkConnection:
    """Manages the state of a single connection to a TeamTalk server."""

    def __init__(
        self,
        server_info: PytalkTeamTalkServerInfo,
        pytalk_bot: pytalk.TeamTalkBot,
        session_factory: Any,
        app_config: Any,
    ):
        """Initializes a TeamTalkConnection instance.

        Args:
            server_info: Information about the TeamTalk server.
            pytalk_bot: The Pytalk.TeamTalkBot instance.
            session_factory: SQLAlchemy session factory.
            app_config: The application's configuration object.
        """
        self.server_info = server_info
        self.pytalk_bot = pytalk_bot
        self.session_factory = session_factory
        self.app_config = app_config  # Store app_config for intervals etc.

        self.instance: pytalk.instance.TeamTalkInstance | None = None
        self.login_complete_time: datetime | None = None

        self.online_users_cache: dict[int, pytalk.user.User] = {}
        self.user_accounts_cache: dict[str, pytalk.UserAccount] = {}  # Key is username string

        self._periodic_sync_task: asyncio.Task[Any] | None = None
        self._populate_accounts_task: asyncio.Task[Any] | None = None
        self._is_finalized = False

    async def connect(self) -> bool:
        """Establishes a connection to the TeamTalk server.

        Adds the server to the PytalkBot instance and sets up the local instance reference.

        Returns:
            True if connection setup was initiated successfully, False otherwise.
        """
        logger.info("Attempting to add server %s:%s to PytalkBot.", self.server_info.host, self.server_info.tcp_port)
        try:
            num_instances_before = len(self.pytalk_bot.teamtalks)
            # self.server_info is already PytalkTeamTalkServerInfo, so pytalk_bot.add_server can use it directly.
            await self.pytalk_bot.add_server(self.server_info)
            num_instances_after = len(self.pytalk_bot.teamtalks)

            if num_instances_after > num_instances_before:
                self.instance = self.pytalk_bot.teamtalks[-1]
                logger.info("Successfully added server %s. Instance created: %s", self.server_info.host, self.instance)
                self._is_finalized = False
                self.login_complete_time = None
                return True
            else:
                logger.error("Failed to add server %s: PytalkBot.teamtalks list did not change.", self.server_info.host)
                return False
        except Exception as e:
            logger.exception("Exception during pytalk_bot.add_server for %s: %s", self.server_info.host, e)
            return False

    async def _periodic_cache_sync(self) -> None:
        if not self.instance:
            logger.error("[%s] Cannot start periodic cache sync: TeamTalk instance is not set.", self.server_info.host)
            return

        logger.info("[%s] Starting periodic online users cache sync.", self.server_info.host)
        ttstr = pytalk.instance.sdk.ttstr
        while True:
            try:
                if self.instance and self.instance.connected and self.instance.logged_in:
                    logger.debug("[%s] Periodic online users cache sync...", self.server_info.host)
                    server_users = self.instance.server.get_users()
                    new_cache = {user.id: user for user in server_users if hasattr(user, "id")}

                    current_ids = set(self.online_users_cache.keys())
                    new_ids = set(new_cache.keys())
                    added_users = new_ids - current_ids
                    removed_users = current_ids - new_ids

                    if added_users:
                        added_usernames = [ttstr(new_cache[uid].username) for uid in added_users]
                        logger.debug("[%s] Users added to cache: %s", self.server_info.host, added_usernames)
                    if removed_users:
                        removed_usernames = [ttstr(self.online_users_cache[uid].username) for uid in removed_users]
                        logger.debug("[%s] Users removed from cache: %s", self.server_info.host, removed_usernames)

                    self.online_users_cache.clear()
                    self.online_users_cache.update(new_cache)
                    logger.debug(
                        "[%s] Online users cache synchronized. Users online: %s.",
                        self.server_info.host,
                        len(self.online_users_cache),
                    )
                else:
                    logger.warning(
                        "[%s] Skipping periodic online users cache sync: "
                        "TT instance not ready (connected: %s, logged_in: %s).",
                        self.server_info.host,
                        self.instance.connected if self.instance else "N/A",
                        self.instance.logged_in if self.instance else "N/A",
                    )
                    await asyncio.sleep(self.app_config.operational_parameters.tt_reconnect_check_interval_seconds)
                    continue
            except TimeoutError as e_timeout:
                logger.exception(
                    "[%s] TimeoutError during periodic online users cache sync: %s.",
                    self.server_info.host,
                    e_timeout,
                )
                await asyncio.sleep(
                    self.app_config.operational_parameters.online_users_cache_sync_interval_seconds // 2
                )
            except pytalk.exceptions.TeamTalkException as e_pytalk:
                logger.exception(
                    "[%s] Pytalk error during periodic online users cache sync: %s.",
                    self.server_info.host,
                    e_pytalk,
                )
                sleep_duration = (
                    self.app_config.operational_parameters.tt_reconnect_retry_seconds
                    if self.instance and self.instance.connected and self.instance.logged_in
                    else self.app_config.operational_parameters.tt_reconnect_check_interval_seconds
                )
                await asyncio.sleep(sleep_duration)
            except Exception as e:
                logger.exception(
                    "[%s] Unexpected error during periodic online users cache sync: %s",
                    self.server_info.host,
                    e,
                )
                await asyncio.sleep(self.app_config.operational_parameters.online_users_cache_sync_interval_seconds)
            await asyncio.sleep(self.app_config.operational_parameters.online_users_cache_sync_interval_seconds)

    async def populate_user_accounts_cache(self) -> None:
        """Populates the cache of user accounts from the TeamTalk server.

        Requires the bot to be an administrator on the server.
        """
        if not self.is_ready:  # Use is_ready property
            logger.warning(
                "[%s] Cannot populate user accounts cache: TeamTalk instance not ready.", self.server_info.host
            )
            return

        logger.info("[%s] Populating user accounts cache...", self.server_info.host)
        ttstr = pytalk.instance.sdk.ttstr
        try:
            if self.instance:  # Ensure instance is not None
                all_accounts = await self.instance.list_user_accounts()
                if all_accounts:  # Ensure all_accounts is not None before iterating
                    self.user_accounts_cache.clear()
                    for acc in all_accounts:
                        username_str = ttstr(acc.username) if isinstance(acc.username, bytes) else str(acc.username)
                        if username_str:
                            self.user_accounts_cache[username_str] = acc
                logger.info(
                    "[%s] User accounts cache populated with %s accounts.",
                    self.server_info.host,
                    len(self.user_accounts_cache),
                )
        except TimeoutError as e_timeout:
            logger.exception("[%s] TimeoutError populating user accounts cache: %s.", self.server_info.host, e_timeout)
        except pytalk.exceptions.PermissionError as e_perm:
            logger.exception(
                "[%s] Pytalk PermissionError populating user accounts cache (Bot might not be admin): %s.",
                self.server_info.host,
                e_perm,
            )
        except pytalk.exceptions.TeamTalkException as e_pytalk:
            logger.exception(
                "[%s] Pytalk error populating user accounts cache: %s.",
                self.server_info.host,
                e_pytalk,
            )
        except Exception as e:
            logger.exception("[%s] Unexpected error populating user accounts cache: %s", self.server_info.host, e)

    def start_background_tasks(self) -> None:
        """Starts background tasks for this connection, like cache synchronization."""
        if not self.instance:
            logger.error("[%s] Cannot start background tasks: TT instance N/A.", self.server_info.host)
            return
        if self._periodic_sync_task is None or self._periodic_sync_task.done():
            self._periodic_sync_task = asyncio.create_task(self._periodic_cache_sync())
            logger.info("[%s] Periodic online users cache sync task started/restarted.", self.server_info.host)
        if self._populate_accounts_task is None or self._populate_accounts_task.done():
            self._populate_accounts_task = asyncio.create_task(self.populate_user_accounts_cache())
            logger.info("[%s] User accounts cache population task started/restarted.", self.server_info.host)

    async def stop_background_tasks(self) -> None:
        """Stops all running background tasks for this connection."""
        logger.info("[%s] Stopping background tasks...", self.server_info.host)
        task_definitions = [
            ("_periodic_sync_task", "_periodic_sync_task"),
            ("_populate_accounts_task", "_populate_accounts_task"),
        ]
        for task_name, task_obj_attr in task_definitions:
            task = getattr(self, task_obj_attr, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info("[%s] Task %s cancelled.", self.server_info.host, task_name)
                except Exception as e:
                    logger.exception("[%s] Error stopping task %s: %s", self.server_info.host, task_name, e)
            setattr(self, task_obj_attr, None)
        logger.info("[%s] Background tasks stopped.", self.server_info.host)

    async def disconnect_instance(self) -> None:
        """Disconnects the TeamTalk instance and cleans up resources."""
        await self.stop_background_tasks()
        if self.instance:
            logger.info("[%s] Disconnecting TeamTalk instance...", self.server_info.host)
            try:
                if self.instance.logged_in:
                    self.instance.logout()
                if self.instance.connected:
                    self.instance.disconnect()
                logger.info("[%s] Instance disconnected procedures called.", self.server_info.host)
            except Exception as e:
                logger.exception("[%s] Error during instance disconnect: %s", self.server_info.host, e)
        self._is_finalized = False
        self.login_complete_time = None

    @property
    def is_ready(self) -> bool:
        """Checks if the TeamTalk instance is connected and logged in."""
        return self.instance is not None and self.instance.connected and self.instance.logged_in

    @property
    def is_finalized(self) -> bool:
        """Checks if the connection's login sequence has been finalized."""
        return self._is_finalized

    def mark_finalized(self, status: bool = True) -> None:
        """Marks the connection's login sequence as finalized or not."""
        self._is_finalized = status
        logger.info(
            "[%s] Connection marked as %s.",
            self.server_info.host,
            "finalized" if status else "NOT finalized",
        )

    def update_caches_on_event(self, event_type: str, data: Any) -> None:
        """Updates internal caches based on incoming TeamTalk user or account events.

        Args:
            event_type: The type of the event (e.g., "user_login", "user_account_new").
            data: The event data object (typically a Pytalk User or UserAccount).
        """
        ttstr = pytalk.instance.sdk.ttstr
        user_id = getattr(data, "id", None)
        username_attr = getattr(data, "username", None)
        username_str = ttstr(username_attr) if username_attr else "UnknownUser"

        if event_type in ["user_login", "user_join", "user_update"]:
            user_data: pytalk.user.User = data
            if user_id is not None:
                self.online_users_cache[user_id] = user_data
                logger.debug(
                    "[%s] User %s (%s) %s -> online_users_cache. Size: %s",
                    self.server_info.host,
                    user_id,
                    username_str,
                    event_type,
                    len(self.online_users_cache),
                )
            else:
                logger.warning(
                    "[%s] User event %s for %s but no ID. Cache not updated.",
                    self.server_info.host,
                    event_type,
                    username_str,
                )
        elif event_type == "user_logout":
            if user_id is not None and user_id in self.online_users_cache:
                del self.online_users_cache[user_id]
                logger.debug(
                    "[%s] User %s (%s) logged out. Removed from online_users_cache. Size: %s",
                    self.server_info.host,
                    user_id,
                    username_str,
                    len(self.online_users_cache),
                )
            elif user_id:
                logger.warning(
                    "[%s] User %s (%s) logged out but not in online_users_cache.",
                    self.server_info.host,
                    user_id,
                    username_str,
                )
            else:
                logger.warning(
                    "[%s] User logout for %s but no ID. Cache not updated.", self.server_info.host, username_str
                )
        elif event_type == "user_account_new":
            new_account: pytalk.UserAccount = data
            raw_username = new_account.username
            acc_username_str = ttstr(raw_username) if isinstance(raw_username, bytes) else str(raw_username)
            if acc_username_str:
                self.user_accounts_cache[acc_username_str] = new_account
                logger.debug(
                    "[%s] User account '%s' added. user_accounts_cache size: %s",
                    self.server_info.host,
                    acc_username_str,
                    len(self.user_accounts_cache),
                )
        elif event_type == "user_account_remove":
            removed_account: pytalk.UserAccount = data
            raw_username = removed_account.username
            acc_username_str = ttstr(raw_username) if isinstance(raw_username, bytes) else str(raw_username)
            if acc_username_str and acc_username_str in self.user_accounts_cache:
                del self.user_accounts_cache[acc_username_str]
                logger.debug(
                    "[%s] User account '%s' removed. user_accounts_cache size: %s",
                    self.server_info.host,
                    acc_username_str,
                    len(self.user_accounts_cache),
                )

    def __repr__(self) -> str:
        """Returns a string representation of the TeamTalkConnection object."""
        instance_id = id(self.instance) if self.instance else None
        return (
            f"<TeamTalkConnection host={self.server_info.host} port={self.server_info.tcp_port} "
            f"instance_id={instance_id} finalized={self.is_finalized}>"
        )
