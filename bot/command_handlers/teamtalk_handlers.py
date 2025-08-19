"""Command handlers that interact with the TeamTalk connection."""

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
        translator: NullTranslations,
        report_service: ReportService,
    ) -> None:
        """Initializes the TeamTalkCommandHandlers.

        Args:
            tt_connection: The TeamTalk connection instance.
            translator: The translator instance.
            report_service: The service for generating reports.
        """
        self._tt_connection = tt_connection
        self._translator = translator
        self._report_service = report_service
        self._ = self._translator.gettext

    async def handle_get_online_users(
        self, command: GetOnlineUsersCommand
    ) -> GetOnlineUsersResult:
        """Handles the command to get online users."""
        if not self._tt_connection or not self._tt_connection.is_ready:
            return GetOnlineUsersResult(
                success=False, error_message="TeamTalk connection is not active."
            )

        report_text = self._report_service.get_online_users_report(
            tt_connection=self._tt_connection,
            is_caller_admin=command.is_caller_admin,
            translator=self._translator,
        )
        return GetOnlineUsersResult(success=True, report_text=report_text)

    async def handle_kick_user(self, command: KickUserCommand) -> ModerationResult:
        """Handles the command to kick a user."""
        return await self._apply_moderation(
            user_id=command.user_id,
            admin_telegram_id=command.admin_telegram_id,
            action="kick",
        )

    async def handle_ban_user(self, command: BanUserCommand) -> ModerationResult:
        """Handles the command to ban a user."""
        return await self._apply_moderation(
            user_id=command.user_id,
            admin_telegram_id=command.admin_telegram_id,
            action="ban",
        )

    async def _apply_moderation(
        self, user_id: int, admin_telegram_id: int, action: str
    ) -> ModerationResult:
        """Generic method to apply kick or ban."""
        if not self._tt_connection or not self._tt_connection.instance:
            return ModerationResult(
                success=False, message=self._("Error: No active TeamTalk connection.")
            )

        user_to_act_on = self._tt_connection.instance.get_user(user_id)
        server_host = self._tt_connection.server_info.host

        if not user_to_act_on:
            msg = self._("User not found on server {server_host} anymore.").format(
                server_host=server_host
            )
            return ModerationResult(success=False, message=msg)

        user_nickname = get_tt_user_display_name(user_to_act_on, self._translator)

        try:
            if action == "kick":
                user_to_act_on.kick(from_server=True)
                logger.info(
                    "Admin %s kicked TT user '%s' (ID: %s)",
                    admin_telegram_id,
                    user_nickname,
                    user_id,
                )
                msg = self._(
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
                msg = self._(
                    "User {user_nickname} banned and kicked from server {server_host}."
                ).format(user_nickname=escape(user_nickname), server_host=server_host)
                return ModerationResult(success=True, message=msg)
        except (PytalkPermissionError, PytalkException):
            logger.exception("Error during '%s' on TT user ID %s", action, user_id)
            return ModerationResult(
                success=False,
                message=self._("An error occurred. Please try again later."),
            )

        return ModerationResult(success=False, message=self._("Unknown action."))
