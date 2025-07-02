import enum
from datetime import datetime
from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship

from bot.core.enums import DeeplinkAction
from bot.core.languages import Language


class NotificationSetting(str, enum.Enum):
    ALL = "all"
    JOIN_OFF = "join_off"
    LEAVE_OFF = "leave_off"
    NONE = "none"


class MuteListMode(str, enum.Enum):
    blacklist = "blacklist"
    whitelist = "whitelist"


class UserSettings(SQLModel, table=True):
    __tablename__ = "user_settings"

    telegram_id: int = Field(default=None, primary_key=True, index=True)
    language: Language = Field(default=Language.ENGLISH, nullable=False)
    notification_settings: NotificationSetting = Field(default=NotificationSetting.ALL, nullable=False)
    mute_list_mode: "MuteListMode" = Field(default=MuteListMode.blacklist, nullable=False)
    teamtalk_username: Optional[str] = Field(default=None, index=True)
    not_on_online_enabled: bool = Field(default=False, nullable=False)
    not_on_online_confirmed: bool = Field(default=False, nullable=False)

    # Relationship to MutedUser table
    muted_users_list: List["MutedUser"] = Relationship(back_populates="user_settings")


class MutedUser(SQLModel, table=True):
    __tablename__ = "muted_users"

    id: Optional[int] = Field(default=None, primary_key=True)
    muted_teamtalk_username: str = Field(index=True, nullable=False)

    # Foreign key to UserSettings table
    user_settings_telegram_id: int = Field(foreign_key="user_settings.telegram_id", nullable=False)

    # Relationship back to UserSettings
    user_settings: "UserSettings" = Relationship(back_populates="muted_users_list")


class SubscribedUser(SQLModel, table=True):
    __tablename__ = "subscribed_users"
    telegram_id: int = Field(default=None, primary_key=True, index=True)


class Admin(SQLModel, table=True):
    __tablename__ = "admins"
    telegram_id: int = Field(default=None, primary_key=True, index=True)


class Deeplink(SQLModel, table=True):
    __tablename__ = "deeplinks"
    token: str = Field(default=None, primary_key=True, index=True)
    action: DeeplinkAction = Field(nullable=False)
    payload: Optional[str] = Field(default=None)
    expected_telegram_id: Optional[int] = Field(default=None)
    expiry_time: datetime = Field(nullable=False)
