"""Pydantic models specific to Telegram bot operations, not database tables."""

from pydantic import BaseModel


class SubscriberInfo(BaseModel):
    """Pydantic model for subscriber information for display purposes."""

    telegram_id: int
    display_name: str
    teamtalk_username: str | None = None


class WhoUser(BaseModel):
    """Pydantic model representing a user in the /who command output."""

    nickname: str


class WhoChannelGroup(BaseModel):
    """Pydantic model for a group of users in a channel for /who command output."""

    channel_name: str
    users: list[WhoUser]
