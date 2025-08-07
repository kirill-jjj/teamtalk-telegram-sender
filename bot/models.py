"""SQLModel definitions for database tables."""

from datetime import datetime
import enum
from typing import Any

from sqlalchemy import CheckConstraint
from sqlmodel import Field, Relationship, SQLModel

from bot.core.enums import DeeplinkAction


class NotificationSetting(str, enum.Enum):
    """Enum for user notification preferences."""

    ALL = "all"
    JOIN_OFF = "join_off"
    LEAVE_OFF = "leave_off"
    NONE = "none"


class MuteListMode(str, enum.Enum):
    """Enum for mute list behavior (blacklist or whitelist)."""

    blacklist = "blacklist"
    whitelist = "whitelist"


class UserSettings(SQLModel, table=True):
    """Represents user-specific settings stored in the database."""

    __tablename__ = "user_settings"

    telegram_id: int = Field(default=None, primary_key=True, index=True)
    language_code: str = Field(nullable=False)
    notification_settings: NotificationSetting = Field(
        default=NotificationSetting.ALL, nullable=False
    )
    mute_list_mode: "MuteListMode" = Field(
        default=MuteListMode.blacklist, nullable=False
    )
    teamtalk_username: str | None = Field(default=None, index=True)
    not_on_online_enabled: bool = Field(default=False, nullable=False)
    not_on_online_confirmed: bool = Field(default=False, nullable=False)

    # Relationship to MutedUser table
    muted_users_list: list["MutedUser"] = Relationship(
        back_populates="user_settings",
        cascade_delete=True,
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class MutedUser(SQLModel, table=True):
    """Represents a TeamTalk user muted by a specific Telegram user."""

    __tablename__ = "muted_users"

    id: int | None = Field(default=None, primary_key=True)
    muted_teamtalk_username: str = Field(index=True, nullable=False)

    # Foreign key to UserSettings table
    user_settings_telegram_id: int = Field(
        foreign_key="user_settings.telegram_id", nullable=False
    )

    # Relationship back to UserSettings
    user_settings: "UserSettings" = Relationship(back_populates="muted_users_list")


class SubscribedUser(SQLModel, table=True):
    """Represents a Telegram user subscribed to notifications."""

    __tablename__ = "subscribed_users"
    telegram_id: int = Field(default=None, primary_key=True, index=True)


class Admin(SQLModel, table=True):
    """Represents a Telegram user with administrator privileges for the bot."""

    __tablename__ = "admins"
    telegram_id: int = Field(default=None, primary_key=True, index=True)


class Deeplink(SQLModel, table=True):
    """Represents a deeplink token for actions like subscribe/unsubscribe."""

    __tablename__ = "deeplinks"
    token: str = Field(default=None, primary_key=True, index=True)
    action: DeeplinkAction = Field(nullable=False)
    payload: str | None = Field(default=None)
    expected_telegram_id: int | None = Field(default=None)
    expiry_time: datetime = Field(nullable=False)


class BanList(SQLModel, table=True):
    """Represents an entry in the ban list (for Telegram IDs or TeamTalk usernames)."""

    __tablename__ = "ban_list"

    id: int | None = Field(default=None, primary_key=True)
    # A TG ID can be banned independently
    telegram_id: int | None = Field(default=None, index=True, unique=False)
    # A TT username can be banned independently
    teamtalk_username: str | None = Field(default=None, index=True, unique=False)
    # We might have multiple entries if a user is banned by TG ID and then their
    # TT username is also banned separately, or if one TT user is linked to
    # multiple TG accounts that get banned.
    # `unique=False` allows this. Consider composite unique constraints if
    # specific rules are needed.

    ban_reason: str | None = Field(default=None)
    banned_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    # Constraint to ensure at least one identifier is present
    __table_args__ = (
        CheckConstraint(
            "telegram_id IS NOT NULL OR teamtalk_username IS NOT NULL",
            name="ck_ban_list_identifier_not_both_null",
        ),
    )


# --- Service Operation Result ---


class OperationResult(SQLModel):
    """Represents a structured result for service operations."""

    success: bool
    message_key: str  # For localization key, e.g., "link_tt_account_success_linked"
    message_args: dict[str, Any] | None = Field(
        default=None
    )  # For formatting the localized string
    user_settings: UserSettings | None = Field(
        default=None
    )  # Optional UserSettings object
    long_message: str | None = Field(default=None)  # For detailed reports
