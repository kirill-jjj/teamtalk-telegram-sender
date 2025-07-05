import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError

from bot.models import UserSettings

logger = logging.getLogger(__name__)


async def update_user_settings_in_db(session: AsyncSession, settings: UserSettings) -> bool:
    """
    Updates user settings in the database.
    Cache update is handled by the caller.
    Returns True on success, False on failure.
    """
    session.add(settings)
    try:
        await session.commit()
        await session.refresh(settings)
        # Ensure muted_users_list is refreshed for consistency,
        # though eager loading in get_or_create_user_settings and
        # explicit refresh in middleware should typically cover this.
        await session.refresh(settings, attribute_names=['muted_users_list'])
        logger.debug(f"Updated settings for user {settings.telegram_id} in DB.")
        return True
    except SQLAlchemyError as e:
        await session.rollback()
        logger.error(f"Error updating settings for user {settings.telegram_id} in DB: {e}", exc_info=True)
        return False
