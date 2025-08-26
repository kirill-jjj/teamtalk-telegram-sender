"""Pydantic models specific to Telegram bot operations, not database tables."""

from pydantic import BaseModel


class WhoUser(BaseModel):
    """Pydantic model representing a user in the /who command output."""

    nickname: str


class WhoChannelGroup(BaseModel):
    """Pydantic model for a group of users in a channel for /who command output."""

    channel_name: str
    users: list[WhoUser]


class WhoReport(BaseModel):
    """Pydantic model for the structured /who command report."""

    server_name: str | None
    total_users: int
    grouped_data: list[WhoChannelGroup]
