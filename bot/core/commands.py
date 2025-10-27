"""Defines commands and their result models for the CommandBus."""

from pydantic import BaseModel

from bot.command_bus.types import BaseCommand
from bot.services.schemas import UserAccountInfo, UserDTO


# --- GetOnlineUsers Command ---
class GetOnlineUsersResult(BaseModel):
    """Represents the result of getting online users."""

    success: bool
    users: list[UserDTO] = []
    server_name: str | None = None
    error_message: str | None = None


class GetOnlineUsersCommand(BaseCommand):
    """A command to get the list of online users from TeamTalk."""

    is_caller_admin: bool
    lang_code: str


# --- User Moderation Commands (Kick/Ban) ---
class ModerationResult(BaseModel):
    """Represents the result of a moderation action."""

    success: bool
    message: str


class KickUserCommand(BaseCommand):
    """A command to kick a user from the TeamTalk server."""

    user_id: int
    admin_telegram_id: int
    lang_code: str


class BanUserCommand(BaseCommand):
    """A command to ban a user from the TeamTalk server."""

    user_id: int
    admin_telegram_id: int
    lang_code: str


# --- GetAllTeamTalkAccounts Command ---
class GetAllTeamTalkAccountsResult(BaseModel):
    """Represents the result of getting all user accounts."""

    success: bool
    accounts: list[UserAccountInfo] = []
    error_message: str | None = None


class GetAllTeamTalkAccountsCommand(BaseCommand):
    """A command to get the list of all user accounts from a TeamTalk server."""

    lang_code: str
