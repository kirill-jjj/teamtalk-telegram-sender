import pytalk
import asyncio
import logging
from datetime import datetime
from typing import Any # For app_config_instance type hint

# Assuming TeamTalkServerInfo is from pytalk.enums or defined if custom
# For this context, we'll assume it's compatible with what pytalk_bot.add_server expects
# If bot.config.TeamTalkServerInfo is the actual Pydantic model, Application will create pytalk.TeamTalkServerInfo from it.
# For now, using pytalk.TeamTalkServerInfo directly for clarity in this class.
from pytalk.enums import TeamTalkServerInfo as PytalkTeamTalkServerInfo

# Assuming SessionFactory is a known type, e.g., from sqlalchemy.orm or a custom definition
# For type hinting, it can be `Any` if not strictly defined here.
# from bot.database.engine import SessionFactory # Example if it's defined elsewhere

logger = logging.getLogger(__name__)

class TeamTalkConnection:
    """
    Manages the state of a single connection to a TeamTalk server.
    """
    def __init__(self, server_info: PytalkTeamTalkServerInfo, pytalk_bot: pytalk.TeamTalkBot, session_factory: Any, app_config: Any):
        self.server_info = server_info
        self.pytalk_bot = pytalk_bot
        self.session_factory = session_factory
        self.app_config = app_config # Store app_config for intervals etc.

        self.instance: pytalk.instance.TeamTalkInstance | None = None
        self.login_complete_time: datetime | None = None

        self.online_users_cache: dict[int, pytalk.user.User] = {}
        self.user_accounts_cache: dict[str, pytalk.UserAccount] = {} # Key is username string

        self._periodic_sync_task: asyncio.Task | None = None
        self._populate_accounts_task: asyncio.Task | None = None
        self._is_finalized = False

    async def connect(self) -> bool:
        logger.info(f"Attempting to add server {self.server_info.host}:{self.server_info.tcp_port} to PytalkBot.")
        try:
            num_instances_before = len(self.pytalk_bot.teamtalks)
            # self.server_info is already PytalkTeamTalkServerInfo, so pytalk_bot.add_server can use it directly.
            await self.pytalk_bot.add_server(self.server_info)
            num_instances_after = len(self.pytalk_bot.teamtalks)

            if num_instances_after > num_instances_before:
                self.instance = self.pytalk_bot.teamtalks[-1]
                logger.info(f"Successfully added server {self.server_info.host}. Instance created: {self.instance}")
                self._is_finalized = False
                self.login_complete_time = None
                return True
            else:
                logger.error(f"Failed to add server {self.server_info.host}: PytalkBot.teamtalks list did not change.")
                return False
        except Exception as e:
            logger.error(f"Exception during pytalk_bot.add_server for {self.server_info.host}: {e}", exc_info=True)
            return False

    async def _periodic_cache_sync(self):
        if not self.instance:
            logger.error(f"[{self.server_info.host}] Cannot start periodic cache sync: TeamTalk instance is not set.")
            return

        logger.info(f"[{self.server_info.host}] Starting periodic online users cache sync.")
        ttstr = pytalk.instance.sdk.ttstr
        while True:
            try:
                if self.instance and self.instance.connected and self.instance.logged_in:
                    logger.debug(f"[{self.server_info.host}] Performing periodic online users cache synchronization...")
                    server_users = self.instance.server.get_users()
                    new_cache = {user.id: user for user in server_users if hasattr(user, 'id')}

                    current_ids = set(self.online_users_cache.keys())
                    new_ids = set(new_cache.keys())
                    added_users = new_ids - current_ids
                    removed_users = current_ids - new_ids

                    if added_users: logger.debug(f"[{self.server_info.host}] Users added to cache: {[ttstr(new_cache[uid].username) for uid in added_users]}")
                    if removed_users: logger.debug(f"[{self.server_info.host}] Users removed from cache: {[ttstr(self.online_users_cache[uid].username) for uid in removed_users]}")

                    self.online_users_cache.clear()
                    self.online_users_cache.update(new_cache)
                    logger.debug(f"[{self.server_info.host}] Online users cache synchronized. Users online: {len(self.online_users_cache)}.")
                else:
                    logger.warning(f"[{self.server_info.host}] Skipping periodic online users cache sync: TT instance not ready (connected: {self.instance.connected if self.instance else 'N/A'}, logged_in: {self.instance.logged_in if self.instance else 'N/A'}).")
                    await asyncio.sleep(self.app_config.TT_RECONNECT_CHECK_INTERVAL_SECONDS)
                    continue
            except TimeoutError as e_timeout:
                logger.error(f"[{self.server_info.host}] TimeoutError during periodic online users cache sync: {e_timeout}.", exc_info=True)
                await asyncio.sleep(self.app_config.ONLINE_USERS_CACHE_SYNC_INTERVAL_SECONDS // 2)
            except pytalk.exceptions.TeamTalkException as e_pytalk:
                logger.error(f"[{self.server_info.host}] Pytalk error during periodic online users cache sync: {e_pytalk}.", exc_info=True)
                await asyncio.sleep(self.app_config.TT_RECONNECT_RETRY_SECONDS if self.instance and self.instance.connected and self.instance.logged_in else self.app_config.TT_RECONNECT_CHECK_INTERVAL_SECONDS)
            except Exception as e:
                logger.error(f"[{self.server_info.host}] Unexpected error during periodic online users cache sync: {e}", exc_info=True)
                await asyncio.sleep(self.app_config.ONLINE_USERS_CACHE_SYNC_INTERVAL_SECONDS)
            await asyncio.sleep(self.app_config.ONLINE_USERS_CACHE_SYNC_INTERVAL_SECONDS)

    async def populate_user_accounts_cache(self):
        if not self.is_ready: # Use is_ready property
            logger.warning(f"[{self.server_info.host}] Cannot populate user accounts cache: TeamTalk instance not ready.")
            return

        logger.info(f"[{self.server_info.host}] Populating user accounts cache...")
        ttstr = pytalk.instance.sdk.ttstr
        try:
            all_accounts = await self.instance.list_user_accounts()
            self.user_accounts_cache.clear()
            for acc in all_accounts:
                username_str = ttstr(acc.username) if isinstance(acc.username, bytes) else str(acc.username)
                if username_str: self.user_accounts_cache[username_str] = acc
            logger.info(f"[{self.server_info.host}] User accounts cache populated with {len(self.user_accounts_cache)} accounts.")
        except TimeoutError as e_timeout: logger.error(f"[{self.server_info.host}] TimeoutError populating user accounts cache: {e_timeout}.", exc_info=True)
        except pytalk.exceptions.PermissionError as e_perm: logger.error(f"[{self.server_info.host}] Pytalk PermissionError populating user accounts cache (Bot might not be admin): {e_perm}.", exc_info=True)
        except pytalk.exceptions.TeamTalkException as e_pytalk: logger.error(f"[{self.server_info.host}] Pytalk error populating user accounts cache: {e_pytalk}.", exc_info=True)
        except Exception as e: logger.error(f"[{self.server_info.host}] Unexpected error populating user accounts cache: {e}", exc_info=True)

    def start_background_tasks(self):
        if not self.instance:
            logger.error(f"[{self.server_info.host}] Cannot start background tasks: TT instance N/A.")
            return
        if self._periodic_sync_task is None or self._periodic_sync_task.done():
            self._periodic_sync_task = asyncio.create_task(self._periodic_cache_sync())
            logger.info(f"[{self.server_info.host}] Periodic online users cache sync task started/restarted.")
        if self._populate_accounts_task is None or self._populate_accounts_task.done():
            self._populate_accounts_task = asyncio.create_task(self.populate_user_accounts_cache())
            logger.info(f"[{self.server_info.host}] User accounts cache population task started/restarted.")

    async def stop_background_tasks(self):
        logger.info(f"[{self.server_info.host}] Stopping background tasks...")
        for task_name, task_obj_attr in [("_periodic_sync_task", "_periodic_sync_task"), ("_populate_accounts_task", "_populate_accounts_task")]:
            task = getattr(self, task_obj_attr, None)
            if task and not task.done():
                task.cancel()
                try: await task
                except asyncio.CancelledError: logger.info(f"[{self.server_info.host}] Task {task_name} cancelled.")
                except Exception as e: logger.error(f"[{self.server_info.host}] Error stopping task {task_name}: {e}", exc_info=True)
            setattr(self, task_obj_attr, None)
        logger.info(f"[{self.server_info.host}] Background tasks stopped.")

    async def disconnect_instance(self):
        await self.stop_background_tasks()
        if self.instance:
            logger.info(f"[{self.server_info.host}] Disconnecting TeamTalk instance...")
            try:
                if self.instance.logged_in: self.instance.logout()
                if self.instance.connected: self.instance.disconnect()
                logger.info(f"[{self.server_info.host}] Instance disconnected procedures called.")
            except Exception as e: logger.error(f"[{self.server_info.host}] Error during instance disconnect: {e}", exc_info=True)
        self._is_finalized = False
        self.login_complete_time = None

    @property
    def is_ready(self) -> bool:
        return self.instance is not None and self.instance.connected and self.instance.logged_in

    @property
    def is_finalized(self) -> bool:
        return self._is_finalized

    def mark_finalized(self, status: bool = True):
        self._is_finalized = status
        logger.info(f"[{self.server_info.host}] Connection marked as {'finalized' if status else 'NOT finalized'}.")

    def update_caches_on_event(self, event_type: str, data: Any):
        ttstr = pytalk.instance.sdk.ttstr
        user_id = getattr(data, 'id', None)
        username_attr = getattr(data, 'username', None)
        username_str = ttstr(username_attr) if username_attr else 'UnknownUser'

        if event_type in ["user_login", "user_join", "user_update"]:
            user: pytalk.user.User = data
            if user_id is not None:
                self.online_users_cache[user_id] = user
                logger.debug(f"[{self.server_info.host}] User {user_id} ({username_str}) {event_type} -> online_users_cache. Size: {len(self.online_users_cache)}")
            else: logger.warning(f"[{self.server_info.host}] User event {event_type} for {username_str} but no ID. Cache not updated.")
        elif event_type == "user_logout":
            user: pytalk.user.User = data
            if user_id is not None and user_id in self.online_users_cache:
                del self.online_users_cache[user_id]
                logger.debug(f"[{self.server_info.host}] User {user_id} ({username_str}) logged out. Removed from online_users_cache. Size: {len(self.online_users_cache)}")
            elif user_id: logger.warning(f"[{self.server_info.host}] User {user_id} ({username_str}) logged out but not in online_users_cache.")
            else: logger.warning(f"[{self.server_info.host}] User logout for {username_str} but no ID. Cache not updated.")
        elif event_type == "user_account_new":
            account: pytalk.UserAccount = data
            acc_username_str = ttstr(account.username) if isinstance(account.username, bytes) else str(account.username)
            if acc_username_str:
                self.user_accounts_cache[acc_username_str] = account
                logger.debug(f"[{self.server_info.host}] User account '{acc_username_str}' added. user_accounts_cache size: {len(self.user_accounts_cache)}")
        elif event_type == "user_account_remove":
            account: pytalk.UserAccount = data
            acc_username_str = ttstr(account.username) if isinstance(account.username, bytes) else str(account.username)
            if acc_username_str and acc_username_str in self.user_accounts_cache:
                del self.user_accounts_cache[acc_username_str]
                logger.debug(f"[{self.server_info.host}] User account '{acc_username_str}' removed. user_accounts_cache size: {len(self.user_accounts_cache)}")

    def __repr__(self) -> str:
        instance_id = id(self.instance) if self.instance else None
        return f"<TeamTalkConnection host={self.server_info.host} port={self.server_info.tcp_port} instance_id={instance_id} finalized={self.is_finalized}>"
