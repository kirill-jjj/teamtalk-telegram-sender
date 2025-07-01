import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, selectinload # Added selectinload

from bot.models import UserSettings
# from bot.config import app_config # No longer needed for TTL

logger = logging.getLogger(__name__)

# Replaced TTLCache with a standard dictionary.
# This will store settings as long as the bot is running.
USER_SETTINGS_CACHE: dict[int, UserSettings] = {}

async def load_user_settings_to_cache(session_factory) -> None:
    logger.info("Loading all user settings into cache...")
    async with session_factory() as session:
        # Use selectinload for eager loading of muted_users_list
        statement = select(UserSettings).options(selectinload(UserSettings.muted_users_list))
        results = await session.execute(statement)
        user_settings_list = results.scalars().all()
        for settings_row in user_settings_list:
            USER_SETTINGS_CACHE[settings_row.telegram_id] = settings_row
    logger.info(f"{len(USER_SETTINGS_CACHE)} user settings loaded into cache.")

async def get_or_create_user_settings(telegram_id: int, session: AsyncSession) -> UserSettings:
    """
    Gets user settings from the cache. If not present,
    loads from DB or creates new ones, then adds to cache.
    """
    if telegram_id in USER_SETTINGS_CACHE:
        return USER_SETTINGS_CACHE[telegram_id]

    # If not in cache, query the DB, eagerly loading muted_users_list.
    # Also eagerly load other potential relationships if they exist and are relevant here.
    user_settings = await session.get(
        UserSettings,
        telegram_id,
        options=[
            selectinload(UserSettings.muted_users_list),
            # Add other selectinload options here if UserSettings has more relationships
            # e.g., selectinload(UserSettings.another_related_list)
        ]
    )
    if user_settings:
        USER_SETTINGS_CACHE[telegram_id] = user_settings
        return user_settings
    else:
        # If not in DB, create new settings
        new_settings = UserSettings(telegram_id=telegram_id)
        session.add(new_settings)
        try:
            await session.commit()
            await session.refresh(new_settings)
            # Eagerly load muted_users_list for the new user as well.
            # This ensures the cached object is consistent.
            await session.refresh(new_settings, attribute_names=['muted_users_list'])
            # If other relationships were added above, refresh them too:
            # await session.refresh(new_settings, attribute_names=['muted_users_list', 'another_related_list'])
            logger.debug(f"Created default UserSettings row for user {telegram_id} in DB.")
            USER_SETTINGS_CACHE[telegram_id] = new_settings
            return new_settings
        except Exception as e:
            await session.rollback()
            logger.error(f"Error creating default settings for user {telegram_id}: {e}", exc_info=True)
            # Return a transient default object in case of error to prevent crashes
            return UserSettings(telegram_id=telegram_id)


async def update_user_settings_in_db(session: AsyncSession, settings: UserSettings):
    session.add(settings)
    try:
        await session.commit()
        # Refresh the main object and its relationships to ensure the cached object is up-to-date.
        await session.refresh(settings)
        await session.refresh(settings, attribute_names=['muted_users_list'])
        # If other relationships are managed, refresh them too:
        # await session.refresh(settings, attribute_names=['muted_users_list', 'another_related_list'])
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
