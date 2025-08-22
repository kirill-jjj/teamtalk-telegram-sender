"""Command handlers that interact with the TeamTalk connection."""

from collections.abc import Callable
from gettext import NullTranslations
from html import escape
import logging

from pytalk.exceptions import PermissionError as PytalkPermissionError
from pytalk.exceptions import TeamTalkException as PytalkException

from bot.commands import (
    BanUserCommand,
    GetOnlineUsersCommand,
    GetOnlineUsersResult,
    KickUserCommand,
    ModerationResult,
)
from bot.services.report_service import ReportService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.formatters import get_tt_user_display_name

logger = logging.getLogger(__name__)


class TeamTalkCommandHandlers:
    """Container for TeamTalk-related command handlers."""

    def __init__(
        self,
        tt_connection: TeamTalkConnection,
        translator_factory: Callable[[str], NullTranslations],
        report_service: ReportService,
    ) -> None:
        """Initializes the TeamTalkCommandHandlers.

        Args:
            tt_connection: The TeamTalk connection instance.
            translator_factory: The translator factory instance.
            report_service: The service for generating reports.
        """
        self._tt_connection = tt_connection
        self._translator_factory = translator_factory
        self._report_service = report_service

    async def get_online_users(
        self, command: GetOnlineUsersCommand
    ) -> GetOnlineUsersResult:
        """Handles the command to get online users."""
        if not self._tt_connection or not self._tt_connection.is_ready:
            return GetOnlineUsersResult(
                success=False, error_message="TeamTalk connection is not active."
            )

        translator = self._translator_factory(command.lang_code)
        _ = translator.gettext

        report_text = self._report_service.get_online_users_report(
            tt_connection=self._tt_connection,
            is_caller_admin=command.is_caller_admin,
            translator=translator,
        )
        return GetOnlineUsersResult(
            success=True,
            report_text=report_text,
            users=list(self._tt_connection.cache_manager.online_users_cache.values()),
        )

    async def kick_user(self, command: KickUserCommand) -> ModerationResult:
        """Handles the command to kick a user."""
        translator = self._translator_factory(
            "en"
        )  # Default to English for moderation messages
        _ = translator.gettext
        return await self._apply_moderation(
            user_id=command.user_id,
            admin_telegram_id=command.admin_telegram_id,
            action="kick",
            translator=translator,
        )

    async def ban_user(self, command: BanUserCommand) -> ModerationResult:
        """Handles the command to ban a user."""
        translator = self._translator_factory(
            "en"
        )  # Default to English for moderation messages
        _ = translator.gettext
        return await self._apply_moderation(
            user_id=command.user_id,
            admin_telegram_id=command.admin_telegram_id,
            action="ban",
            translator=translator,
        )

    async def _apply_moderation(
        self,
        user_id: int,
        admin_telegram_id: int,
        action: str,
        translator: NullTranslations,
    ) -> ModerationResult:
        """Generic method to apply kick or ban."""
        _ = translator.gettext
        if not self._tt_connection or not self._tt_connection.instance:
            return ModerationResult(
                success=False, message=_("Error: No active TeamTalk connection.")
            )

        user_to_act_on = self._tt_connection.instance.get_user(user_id)
        server_host = self._tt_connection.server_info.host

        if not user_to_act_on:
            msg = _("User not found on server {server_host} anymore.").format(
                server_host=server_host
            )
            return ModerationResult(success=False, message=msg)

        user_nickname = get_tt_user_display_name(user_to_act_on, translator)

        try:
            if action == "kick":
                user_to_act_on.kick(from_server=True)
                logger.info(
                    "Admin %s kicked TT user '%s' (ID: %s)",
                    admin_telegram_id,
                    user_nickname,
                    user_id,
                )
                msg = _(
                    "User {user_nickname} kicked from server {server_host}."
                ).format(user_nickname=escape(user_nickname), server_host=server_host)
                return ModerationResult(success=True, message=msg)
            if action == "ban":
                user_to_act_on.ban(from_server=True)
                user_to_act_on.kick(from_server=True)
                logger.info(
                    "Admin %s banned and kicked TT user '%s' (ID: %s)",
                    admin_telegram_id,
                    user_nickname,
                    user_id,
                )
                msg = _(
                    "User {user_nickname} banned and kicked from server {server_host}."
                ).format(user_nickname=escape(user_nickname), server_host=server_host)
                return ModerationResult(success=True, message=msg)
        except (PytalkPermissionError, PytalkException):
            logger.exception("Error during '%s' on TT user ID %s", action, user_id)
            return ModerationResult(
                success=False,
                message=_("An error occurred. Please try again later."),
            )

        return ModerationResult(success=False, message=_("Unknown action."))
