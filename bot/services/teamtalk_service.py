"""Service for interacting with the TeamTalk server for read-only data."""

from collections.abc import Callable
from gettext import NullTranslations
import logging

from bot.config import Settings
from bot.services.schemas import TeamTalkFetchResult, UserAccountInfo, UserDTO
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.formatters import (
    get_server_display_name,
    get_tt_user_display_name,
    get_user_display_channel_name,
)

logger = logging.getLogger(__name__)


class TeamTalkService:
    """Service for read-only data retrieval from the TeamTalk server."""

    def __init__(
        self,
        tt_connection: TeamTalkConnection,
        settings: Settings,
        translator_factory: Callable[[str], NullTranslations],
    ) -> None:
        """Initializes the TeamTalkService."""
        self._tt_connection = tt_connection
        self._settings = settings
        self._translator_factory = translator_factory

    async def fetch_online_users(
        self, *, is_caller_admin: bool, lang_code: str
    ) -> TeamTalkFetchResult[UserDTO]:
        """Fetches online users from TeamTalk and returns them as DTOs.

        Returns:
            A TeamTalkFetchResult containing the list of users, server name,
            and an optional error message.
        """
        if not self._tt_connection or not self._tt_connection.is_ready:
            return TeamTalkFetchResult(
                error_message="TeamTalk connection is not active."
            )

        translator = self._translator_factory(lang_code)
        server_name = get_server_display_name(
            self._tt_connection.instance, translator, self._settings
        )

        raw_users = list(self._tt_connection.cache_manager.online_users_cache.values())
        user_dtos = [
            UserDTO(
                id=user.id,
                nickname=get_tt_user_display_name(user, translator),
                channel_name=get_user_display_channel_name(
                    user, is_caller_admin=is_caller_admin, translator=translator
                ),
            )
            for user in raw_users
        ]

        return TeamTalkFetchResult(items=user_dtos, server_name=server_name)

    async def fetch_all_accounts(
        self, lang_code: str
    ) -> TeamTalkFetchResult[UserAccountInfo]:
        """Fetches all user accounts from the TeamTalk server.

        Returns:
            A TeamTalkFetchResult containing the list of accounts and an
            optional error message.
        """
        translator = self._translator_factory(lang_code)
        _ = translator.gettext

        if not self._tt_connection or not self._tt_connection.is_ready:
            return TeamTalkFetchResult(
                error_message=_("Error: No active TeamTalk connection.")
            )

        cache = self._tt_connection.cache_manager.user_accounts_cache
        if not cache:
            return TeamTalkFetchResult(
                error_message=_(
                    "Server user accounts are not loaded yet. "
                    "Please try again in a moment."
                )
            )

        accounts_info = [
            UserAccountInfo(username=acc.username) for acc in cache.values()
        ]

        return TeamTalkFetchResult(items=accounts_info)
