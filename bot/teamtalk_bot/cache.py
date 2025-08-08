"""Manages caches related to a specific TeamTalk server connection."""

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import pytalk

if TYPE_CHECKING:
    from bot.teamtalk_bot.connection import TeamTalkConnection
from pytalk.user import User as PytalkUser
from pytalk.user_account import UserAccount as PytalkUserAccount


class TeamTalkCache:
    """Manages caches for a single TeamTalk server instance."""

    def __init__(self, connection: "TeamTalkConnection") -> None:
        """Initializes the TeamTalkCache."""
        self.connection = connection
        self.settings = connection.settings
        self.online_users_cache: dict[int, PytalkUser] = {}
        self.user_accounts_cache: dict[str, PytalkUserAccount] = {}
        self._periodic_sync_task: asyncio.Task[Any] | None = None
        self._populate_accounts_task: asyncio.Task[Any] | None = None
        self.ttstr = pytalk.instance.sdk.ttstr

    def _get_username_as_str(
        self, user_or_account: PytalkUser | PytalkUserAccount
    ) -> str:
        """Extract username as a string from a TeamTalkUser or TeamTalkUserAccount."""
        username = None
        if hasattr(user_or_account, "username"):
            username = user_or_account.username
        elif hasattr(user_or_account, "_account") and hasattr(
            user_or_account._account, "szUsername"
        ):
            username = user_or_account._account.szUsername
        elif hasattr(user_or_account, "szUsername"):
            username = user_or_account.szUsername
        if isinstance(username, bytes):
            return str(self.ttstr(username))
        return str(username) if username is not None else ""

    async def _periodic_cache_sync(self) -> None:
        """Periodically synchronizes the online users cache with the server."""
        if not self.connection.instance:
            return
        cfg_params = self.settings.operational_parameters
        sync_interval = cfg_params.online_users_cache_sync_interval_seconds
        reconnect_check_interval = cfg_params.tt_reconnect_check_interval_seconds
        while True:
            try:
                if self.connection.is_ready:
                    server_users = self.connection.instance.server.get_users()
                    new_cache = {
                        user.id: user for user in server_users if hasattr(user, "id")
                    }
                    self.online_users_cache.clear()
                    self.online_users_cache.update(new_cache)
                else:
                    await asyncio.sleep(reconnect_check_interval)
                    continue
            except Exception:
                await asyncio.sleep(sync_interval)
            await asyncio.sleep(sync_interval)

    async def populate_user_accounts_cache(self) -> None:
        """Populates the cache of user accounts from the TeamTalk server."""
        if not self.connection.is_ready:
            return
        with contextlib.suppress(Exception):
            if self.connection.instance:
                all_accounts = await self.connection.instance.list_user_accounts()
                if all_accounts:
                    self.user_accounts_cache.clear()
                    for acc in all_accounts:
                        username_str = self.ttstr(acc.username)
                        if username_str:
                            self.user_accounts_cache[username_str] = acc

    def start_background_tasks(self) -> None:
        """Starts background tasks for this connection (cache syncs)."""
        if not self.connection.instance:
            return
        if self._periodic_sync_task is None or self._periodic_sync_task.done():
            self._periodic_sync_task = asyncio.create_task(self._periodic_cache_sync())
        if self._populate_accounts_task is None or self._populate_accounts_task.done():
            self._populate_accounts_task = asyncio.create_task(
                self.populate_user_accounts_cache()
            )

    async def stop_background_tasks(self) -> None:
        """Stops all running background tasks for this connection."""
        tasks_to_stop = [self._periodic_sync_task, self._populate_accounts_task]
        for task in tasks_to_stop:
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    def update_caches_on_event(
        self, event_type: str, data: PytalkUser | PytalkUserAccount
    ) -> None:
        """Updates internal caches based on TeamTalk user or account events."""
        user_id = getattr(data, "id", None)

        if event_type in ["user_login", "user_join", "user_update"]:
            user_data: PytalkUser = data
            if user_id is not None:
                self.online_users_cache[user_id] = user_data
        elif event_type == "user_logout":
            if user_id is not None and user_id in self.online_users_cache:
                del self.online_users_cache[user_id]
        elif event_type == "user_account_new":
            new_acc: PytalkUserAccount = data
            acc_username = self._get_username_as_str(new_acc)
            if acc_username:
                self.user_accounts_cache[acc_username] = new_acc
        elif event_type == "user_account_remove":
            removed_acc: PytalkUserAccount = data
            acc_username = self._get_username_as_str(removed_acc)
            if acc_username and acc_username in self.user_accounts_cache:
                del self.user_accounts_cache[acc_username]
