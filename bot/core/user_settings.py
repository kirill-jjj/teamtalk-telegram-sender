import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload

from bot.models import UserSettings

logger = logging.getLogger(__name__)

USER_SETTINGS_CACHE: dict[int, UserSettings] = {}


async def load_user_settings_to_cache(session_factory) -> None:
    logger.info("Loading all user settings into cache...")
    async with session_factory() as session:
        # Use selectinload for eager loading of related data (muted list)
        statement = select(UserSettings).options(selectinload(UserSettings.muted_users_list))
        results = await session.execute(statement)
        user_settings_list = results.scalars().all()
        for settings_row in user_settings_list:
            USER_SETTINGS_CACHE[settings_row.telegram_id] = settings_row
    logger.info(f"{len(USER_SETTINGS_CACHE)} user settings loaded into cache.")


async def get_or_create_user_settings(telegram_id: int, session: AsyncSession) -> UserSettings:
    """
    Retrieves user settings from the cache. If not present,
    it loads them from the DB or creates new ones, then adds to the cache.
    """
    if telegram_id in USER_SETTINGS_CACHE:
        return USER_SETTINGS_CACHE[telegram_id]

    # If not in cache, search in DB. Eagerly load muted_users_list.
    user_settings = await session.get(
        UserSettings,
        telegram_id,
        options=[selectinload(UserSettings.muted_users_list)]
    )
    if user_settings:
        USER_SETTINGS_CACHE[telegram_id] = user_settings
        return user_settings
    else:
        # Create new settings if they were not in the DB either
        new_settings = UserSettings(telegram_id=telegram_id)
        session.add(new_settings)
        try:
            await session.commit()
            await session.refresh(new_settings)
            # Eagerly load muted_users_list for the new user as well
            await session.refresh(new_settings, attribute_names=['muted_users_list'])
            logger.debug(f"Created default UserSettings row for user {telegram_id} in DB.")
            USER_SETTINGS_CACHE[telegram_id] = new_settings
            return new_settings
        except Exception as e:
            await session.rollback()
            logger.error(f"Error creating default settings for user {telegram_id}: {e}", exc_info=True)
            # Return a temporary object in case of an error, so the bot doesn't crash
            return UserSettings(telegram_id=telegram_id)


async def update_user_settings_in_db(session: AsyncSession, settings: UserSettings):
    session.add(settings)
    try:
        await session.commit()
        await session.refresh(settings)
        # Ensure that related data is also updated
        await session.refresh(settings, attribute_names=['muted_users_list'])
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
