# bot/models.py
import enum
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from bot.core.enums import DeeplinkAction


# Enum для настроек уведомлений, перенесен из старого models.py
class NotificationSetting(str, enum.Enum):
    ALL = "all"
    JOIN_OFF = "join_off"
    LEAVE_OFF = "leave_off"
    NONE = "none"


# Единая модель для настроек пользователя.
# Заменяет UserSettings из bot/database/models.py и UserSpecificSettings из bot/core/user_settings.py
class UserSettings(SQLModel, table=True):
    __tablename__ = "user_settings"

    telegram_id: int = Field(default=None, primary_key=True, index=True)
    language: str = Field(default="en", nullable=False)
    notification_settings: NotificationSetting = Field(default=NotificationSetting.ALL, nullable=False)
    muted_users: str = Field(default="", nullable=False) # Stored as comma-separated string
    mute_all: bool = Field(default=False, nullable=False)
    teamtalk_username: Optional[str] = Field(default=None, index=True)
    not_on_online_enabled: bool = Field(default=False, nullable=False)
    not_on_online_confirmed: bool = Field(default=False, nullable=False)


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
