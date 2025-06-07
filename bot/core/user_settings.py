import logging
import asyncio
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.database.models import UserSettings, NotificationSetting
from bot.config import app_config

logger = logging.getLogger(__name__)

@dataclass
class UserSpecificSettings:
    language: str = field(default_factory=lambda: app_config["EFFECTIVE_DEFAULT_LANG"])
    notification_settings: NotificationSetting = NotificationSetting.ALL
    muted_users_set: set[str] = field(default_factory=set)
    mute_all_flag: bool = False
    teamtalk_username: str | None = None
    not_on_online_enabled: bool = False
    not_on_online_confirmed: bool = False

    @classmethod
    def from_db_row(cls, settings_row: UserSettings | None):
        if not settings_row:
            return cls()
        return cls(
            language=settings_row.language,
            notification_settings=settings_row.notification_settings,
            muted_users_set=set(settings_row.muted_users.split(",")) if settings_row.muted_users else set(),
            mute_all_flag=settings_row.mute_all,
            teamtalk_username=settings_row.teamtalk_username,
            not_on_online_enabled=settings_row.not_on_online_enabled,
            not_on_online_confirmed=settings_row.not_on_online_confirmed,
        )

def _prepare_muted_users_string(users_set: set[str]) -> str:
    if not users_set: # Handle empty set directly to avoid unnecessary list conversion and sort
        return ""
    return ",".join(sorted(list(users_set)))

USER_SETTINGS_CACHE: dict[int, UserSpecificSettings] = {}

async def load_user_settings_to_cache(session_factory) -> None: # session_factory type: sessionmaker from sqlalchemy.orm
    logger.info("Loading user settings into cache...")
    async with session_factory() as session:
        result = await session.execute(select(UserSettings))
        user_settings_list = result.scalars().all()
        for settings_row in user_settings_list:
            USER_SETTINGS_CACHE[settings_row.telegram_id] = UserSpecificSettings.from_db_row(settings_row)
    logger.debug(f"{len(USER_SETTINGS_CACHE)} user settings loaded into cache.") # Changed to debug

async def get_or_create_user_settings(telegram_id: int, session: AsyncSession) -> UserSpecificSettings:
    """
    Retrieves user settings from cache or DB. If not found, creates default settings in DB and cache.
    This function is intended to be the primary way to get user settings.
    """
    if telegram_id in USER_SETTINGS_CACHE:
        return USER_SETTINGS_CACHE[telegram_id]

    user_settings_row = await session.get(UserSettings, telegram_id)
    if user_settings_row:
        specific_settings = UserSpecificSettings.from_db_row(user_settings_row)
        USER_SETTINGS_CACHE[telegram_id] = specific_settings
        return specific_settings
    else:
        default_settings = UserSpecificSettings()
        new_settings_row = UserSettings(
            telegram_id=telegram_id,
            language=default_settings.language,
            notification_settings=default_settings.notification_settings,
            muted_users=await asyncio.to_thread(_prepare_muted_users_string, default_settings.muted_users_set), # Ensure consistent string format
            mute_all=default_settings.mute_all_flag,
            teamtalk_username=default_settings.teamtalk_username,
            not_on_online_enabled=default_settings.not_on_online_enabled,
            not_on_online_confirmed=default_settings.not_on_online_confirmed,
        )
        session.add(new_settings_row)
        try:
            await session.commit()
            USER_SETTINGS_CACHE[telegram_id] = default_settings
            logger.debug(f"Created default settings for user {telegram_id} in DB and cache.") # Changed to debug
            return default_settings
        except Exception as e:
            await session.rollback()
            logger.error(f"Error creating default settings for user {telegram_id}: {e}")
            # Return a default instance even if DB save fails, to avoid breaking logic relying on settings object
            return UserSpecificSettings()


async def update_user_settings_in_db(session: AsyncSession, telegram_id: int, settings: UserSpecificSettings):
    """Updates the UserSettings in the database and cache."""
    user_settings_row = await session.get(UserSettings, telegram_id)
    if not user_settings_row:
        user_settings_row = UserSettings(telegram_id=telegram_id)
        session.add(user_settings_row)

    user_settings_row.language = settings.language
    user_settings_row.notification_settings = settings.notification_settings
    user_settings_row.muted_users = await asyncio.to_thread(_prepare_muted_users_string, settings.muted_users_set)
    user_settings_row.mute_all = settings.mute_all_flag
    user_settings_row.teamtalk_username = settings.teamtalk_username
    user_settings_row.not_on_online_enabled = settings.not_on_online_enabled
    user_settings_row.not_on_online_confirmed = settings.not_on_online_confirmed

    try:
        await session.commit()
        USER_SETTINGS_CACHE[telegram_id] = settings # Update cache
        logger.debug(f"Updated settings for user {telegram_id} in DB and cache.")
    except Exception as e:
        await session.rollback()
        logger.error(f"Error updating settings for user {telegram_id} in DB: {e}")
