"""Service layer for user-related operations, like profile deletion."""

import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession  # Changed to SQLModel's AsyncSession

from bot.database import crud

if TYPE_CHECKING:
    from bot.services_container import Services  # Import Services

logger = logging.getLogger(__name__)


async def delete_full_user_profile(
    session: AsyncSession,
    telegram_id: int,
    services: "Services",  # Changed from app: "Application"
) -> bool:
    """Orchestrates the full deletion of a user's profile.

    This includes database records and cache entries via the services container.
    """
    logger.info("Attempting to delete full user profile for Telegram ID: %s", telegram_id)
    try:
        user_settings_deleted, subscribed_user_deleted = await crud._delete_user_data_from_db(session, telegram_id)

        if not user_settings_deleted and not subscribed_user_deleted:
            logger.info("No DB data found for Telegram ID %s to delete.", telegram_id)
        else:
            await session.commit()
            logger.debug("Committed DB deletions for %s.", telegram_id)

        # Clear data from caches using the services container
        if telegram_id in services.user_settings_cache:
            del services.user_settings_cache[telegram_id]
            logger.info("Removed user %s from services.user_settings_cache.", telegram_id)

        services.subscribed_users_cache.discard(telegram_id)
        logger.info("User %s discarded from services.subscribed_users_cache.", telegram_id)

        services.admin_ids_cache.discard(telegram_id)  # Also remove from admin cache if they were an admin
        logger.info("User %s discarded from services.admin_ids_cache (if present).", telegram_id)

        logger.info(
            "Full user profile deletion process completed for Telegram ID: %s. "
            "DB changes (if any) committed. Caches cleared via services container.",
            telegram_id,
        )
        return True

    except SQLAlchemyError as e_sql:
        await session.rollback()
        logger.exception("SQLAlchemyError during full data deletion for %s: %s. Rolling back.", telegram_id, e_sql)
        return False
    except Exception as e:
        await session.rollback()
        logger.exception("Unexpected error during full data deletion for %s: %s. Rolling back.", telegram_id, e)
        return False
