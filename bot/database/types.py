"""Enums and custom types for database models."""

from enum import StrEnum


class NotificationSetting(StrEnum):
    """Enum for user notification preferences."""

    ALL = "all"
    JOIN_OFF = "join_off"
    LEAVE_OFF = "leave_off"
    NONE = "none"


class MuteListMode(StrEnum):
    """Enum for mute list behavior (blacklist or whitelist)."""

    blacklist = "blacklist"
    whitelist = "whitelist"
