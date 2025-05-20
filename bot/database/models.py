import enum
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Index
from sqlalchemy import Enum as SQLAEnum
from bot.database.engine import Base
from bot.constants import DEFAULT_LANGUAGE

class SubscribedUser(Base):
    __tablename__ = "subscribed_users"
    telegram_id = Column(Integer, primary_key=True, index=True, autoincrement=False) # Assuming telegram_id is unique and not auto-incrementing

class Admin(Base):
    __tablename__ = "admins"
    telegram_id = Column(Integer, primary_key=True, index=True, autoincrement=False) # Assuming telegram_id is unique

class Deeplink(Base):
    __tablename__ = "deeplinks"
    token = Column(String, primary_key=True, index=True)
    action = Column(String, nullable=False)
    payload = Column(String, nullable=True)
    expected_telegram_id = Column(Integer, nullable=True)
    expiry_time = Column(DateTime, nullable=False)

class NotificationSetting(enum.Enum):
    ALL = "all"
    JOIN_OFF = "join_off"
    LEAVE_OFF = "leave_off"
    NONE = "none"

class UserSettings(Base):
    __tablename__ = "user_settings"
    telegram_id = Column(Integer, primary_key=True, index=True, autoincrement=False) # Assuming telegram_id is unique
    language = Column(String, default=DEFAULT_LANGUAGE, nullable=False)
    notification_settings = Column(SQLAEnum(NotificationSetting), default=NotificationSetting.ALL, nullable=False)
    muted_users = Column(String, default="", nullable=False) # Comma-separated string
    mute_all = Column(Boolean, default=False, nullable=False)
    teamtalk_username = Column(String, nullable=True, index=True)
    not_on_online_enabled = Column(Boolean, default=False, nullable=False)
    not_on_online_confirmed = Column(Boolean, default=False, nullable=False)

    # Explicit index for telegram_id, though primary_key=True often implies an index.
    # __table_args__ = (Index("ix_user_settings_telegram_id", "telegram_id"),) # Already indexed by primary_key
