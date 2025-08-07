"""Core utilities for managing user settings in the database."""

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.models import UserSettings

logger = logging.getLogger(__name__)


async def update_user_settings_in_db(
    session: AsyncSession, settings: UserSettings
) -> bool:
    """Updates user settings in the database.

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
        await session.refresh(settings, attribute_names=["muted_users_list"])
        logger.debug("Updated settings for user %s in DB.", settings.telegram_id)
    except SQLAlchemyError:
        logger.exception(
            "Error updating settings for user %s in DB.", settings.telegram_id
        )
        return False
    else:
        return True
