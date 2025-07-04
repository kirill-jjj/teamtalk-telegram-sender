import logging
from sqlalchemy.ext.asyncio import AsyncSession
# from sqlmodel import select # Not used directly anymore in this file
from sqlalchemy.orm import selectinload # Keep for eager loading
from sqlalchemy.exc import SQLAlchemyError

from bot.models import UserSettings

logger = logging.getLogger(__name__)

# USER_SETTINGS_CACHE global variable is removed. It's now managed by the Application class.

# load_user_settings_to_cache function is removed.
# Its functionality is now part of Application.load_user_settings_to_app_cache().

# get_or_create_user_settings function is removed.
# Its functionality is now part of Application.get_or_create_user_settings().

async def update_user_settings_in_db(session: AsyncSession, settings: UserSettings) -> bool:
    """
    Updates user settings in the database.
    Cache update is handled by the caller (e.g., Application or service layer).
    Returns True on success, False on failure.
    """
    session.add(settings) # Add/merge the settings object to the session
    try:
        await session.commit()
        await session.refresh(settings)
        # Ensure that related data is also updated if necessary by refreshing relationships
        # This is important if 'muted_users_list' is accessed after this call within the same session context by the caller.
        # However, for typical use where the object is re-cached or re-fetched, this specific refresh might not be strictly needed by all callers.
        # For safety and consistency with previous logic, keep it.
        await session.refresh(settings, attribute_names=['muted_users_list'])
        logger.debug(f"Updated settings for user {settings.telegram_id} in DB.")
        return True
    except SQLAlchemyError as e:
        await session.rollback()
        logger.error(f"Error updating settings for user {settings.telegram_id} in DB: {e}", exc_info=True)
        return False

# remove_user_settings_from_cache function is removed.
# Cache removal is handled directly by the Application or service layer
# (e.g., in user_service.delete_full_user_profile using `del app.user_settings_cache[telegram_id]`).
