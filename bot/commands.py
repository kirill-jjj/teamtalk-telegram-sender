"""Defines commands and their result models for the CommandBus."""

from pydantic import BaseModel
import pytalk

from bot.command_bus.types import BaseCommand


# --- GetOnlineUsers Command ---
class GetOnlineUsersResult(BaseModel):
    """Represents the result of getting online users."""

    model_config = {"arbitrary_types_allowed": True}

    success: bool
    users: list[pytalk.user.User] = []
    report_text: str | None = None
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


class BanUserCommand(BaseCommand):
    """A command to ban a user from the TeamTalk server."""

    user_id: int
    admin_telegram_id: int
