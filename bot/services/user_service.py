import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from bot.database import crud
from bot.core.user_settings import remove_user_settings_from_cache
from bot.state import SUBSCRIBED_USERS_CACHE

logger = logging.getLogger(__name__)

async def delete_full_user_profile(session: AsyncSession, telegram_id: int) -> bool:
    """
    Orchestrates the full deletion of a user's profile, including database records and cache entries.
    """
    logger.info(f"Attempting to delete full user profile for Telegram ID: {telegram_id}")
    try:
        # 1. Delete data from the database using the new CRUD helper
        # The CRUD function _delete_user_data_from_db does not commit.
        user_settings_deleted, subscribed_user_deleted = await crud._delete_user_data_from_db(session, telegram_id)

        if not user_settings_deleted and not subscribed_user_deleted:
            logger.info(f"No DB data found for Telegram ID {telegram_id} to delete.")
            # Proceed to clear caches even if no DB data was found, for consistency
        else:
            # Only commit if something was actually marked for deletion in the DB
            await session.commit()
            logger.debug(f"Committed DB deletions for {telegram_id}.")

        # 2. Clear data from caches
        remove_user_settings_from_cache(telegram_id)
        SUBSCRIBED_USERS_CACHE.discard(telegram_id)

        logger.info(f"Full user profile deletion process completed for Telegram ID: {telegram_id}. DB changes (if any) committed. Caches cleared.")
        return True

    except SQLAlchemyError as e_sql:
        await session.rollback()
        logger.error(f"SQLAlchemyError during full data deletion for {telegram_id}: {e_sql}. Rolling back.", exc_info=True)
        return False
