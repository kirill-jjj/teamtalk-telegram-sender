import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from cachetools import TTLCache

from bot.models import UserSettings
from bot.config import app_config

logger = logging.getLogger(__name__)

# Initialize a TTL cache
# maxsize is an estimate, adjust as needed based on expected concurrent users
# ttl is in seconds, from app_config
USER_SETTINGS_CACHE: TTLCache[int, UserSettings] = TTLCache(
    maxsize=1024, ttl=app_config.USER_SETTINGS_CACHE_TTL_SECONDS
)

async def load_user_settings_to_cache(session_factory) -> None:
    logger.info("Loading user settings into cache...")
    # Note: Loading all settings into a TTL cache at startup might not be ideal
    # if the dataset is very large and TTL is short, as they might expire before use.
    # However, for moderate numbers of users or longer TTLs, this pre-populates.
    # Alternatively, the cache can be purely populated on-demand via get_or_create_user_settings.
    # For now, keeping the pre-population logic.
    async with session_factory() as session:
        statement = select(UserSettings)
        results = await session.execute(statement)
        user_settings_list = results.scalars().all()
        for settings_row in user_settings_list:
            USER_SETTINGS_CACHE[settings_row.telegram_id] = settings_row
    logger.debug(f"{len(USER_SETTINGS_CACHE)} user settings loaded into cache.")

async def get_or_create_user_settings(telegram_id: int, session: AsyncSession) -> UserSettings:
    if telegram_id in USER_SETTINGS_CACHE:
        return USER_SETTINGS_CACHE[telegram_id]

    user_settings = await session.get(UserSettings, telegram_id)
    if user_settings:
        USER_SETTINGS_CACHE[telegram_id] = user_settings
        return user_settings
    else:
        new_settings = UserSettings(telegram_id=telegram_id)
        session.add(new_settings)
        try:
            await session.commit()
            await session.refresh(new_settings)
            logger.debug(f"Created default UserSettings row for user {telegram_id} in DB.")
            USER_SETTINGS_CACHE[telegram_id] = new_settings
            return new_settings
        except Exception as e:
            await session.rollback()
            logger.error(f"Error creating default settings for user {telegram_id}: {e}", exc_info=True)
            return UserSettings(telegram_id=telegram_id)


async def update_user_settings_in_db(session: AsyncSession, settings: UserSettings):
    session.add(settings)
    try:
        await session.commit()
        await session.refresh(settings)
        USER_SETTINGS_CACHE[settings.telegram_id] = settings
        logger.debug(f"Updated settings for user {settings.telegram_id} in DB and cache.")
    except Exception as e:
        await session.rollback()
        logger.error(f"Error updating settings for user {settings.telegram_id} in DB: {e}", exc_info=True)

def remove_user_settings_from_cache(telegram_id: int) -> None:
    if telegram_id in USER_SETTINGS_CACHE:
        del USER_SETTINGS_CACHE[telegram_id]
        logger.debug(f"Removed user settings for {telegram_id} from cache.")
    else:
        logger.debug(f"User settings for {telegram_id} not found in cache for removal.")
