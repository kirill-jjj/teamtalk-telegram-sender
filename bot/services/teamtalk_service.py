"""Service for interacting with the TeamTalk server for read-only data."""

from collections.abc import Callable
from gettext import NullTranslations
import logging

from pytalk.exceptions import PytalkPermissionError
from pytalk.exceptions import TeamTalkError as PytalkException

from bot.config import Settings
from bot.core.exceptions import (
    NoActiveTeamTalkConnectionError,
    TeamTalkConnectionError,
    TeamTalkPermissionError,
    TeamTalkUserNotFoundError,
)
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

    @property
    def server_name(self) -> str:
        """Returns the display name of the TeamTalk server."""
        translator = self._translator_factory(self._settings.general.default_lang)
        if not self._tt_connection.instance:
            return "TeamTalk"
        return get_server_display_name(
            self._tt_connection.instance, translator, self._settings
        )

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

    async def kick_user(self, user_id: int) -> UserDTO:
        """Kicks a user from the server."""
        if not self._tt_connection.instance:
            raise NoActiveTeamTalkConnectionError

        user_to_kick = self._tt_connection.instance.get_user(user_id)
        if not user_to_kick:
            raise TeamTalkUserNotFoundError

        translator = self._translator_factory(self._settings.general.default_lang)
        user_dto = UserDTO(
            id=user_to_kick.id,
            nickname=get_tt_user_display_name(user_to_kick, translator),
            channel_name=get_user_display_channel_name(
                user_to_kick, is_caller_admin=True, translator=translator
            ),
        )
        try:
            user_to_kick.kick(from_server=True)
        except PytalkPermissionError as e:
            raise TeamTalkPermissionError from e
        except PytalkException as e:
            raise TeamTalkConnectionError from e
        else:
            return user_dto

    async def ban_user(self, user_id: int) -> UserDTO:
        """Bans a user from the server."""
        if not self._tt_connection.instance:
            raise NoActiveTeamTalkConnectionError

        user_to_ban = self._tt_connection.instance.get_user(user_id)
        if not user_to_ban:
            raise TeamTalkUserNotFoundError

        translator = self._translator_factory(self._settings.general.default_lang)
        user_dto = UserDTO(
            id=user_to_ban.id,
            nickname=get_tt_user_display_name(user_to_ban, translator),
            channel_name=get_user_display_channel_name(
                user_to_ban, is_caller_admin=True, translator=translator
            ),
        )

        try:
            user_to_ban.ban(from_server=True)
            user_to_ban.kick(from_server=True)  # Banning doesn't auto-kick
        except PytalkPermissionError as e:
            raise TeamTalkPermissionError from e
        except PytalkException as e:
            raise TeamTalkConnectionError from e
        else:
            return user_dto
