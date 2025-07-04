import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from typing import TYPE_CHECKING

from bot.database import crud
# from bot.core.user_settings import remove_user_settings_from_cache # Will use app.remove_user_settings_from_cache
# from bot.state import SUBSCRIBED_USERS_CACHE # Will use app.subscribed_users_cache

if TYPE_CHECKING:
    from sender import Application # For type hinting app instance

logger = logging.getLogger(__name__)

async def delete_full_user_profile(
    session: AsyncSession,
    telegram_id: int,
    app: "Application" # Pass Application instance
) -> bool:
    """
    Orchestrates the full deletion of a user's profile,
    including database records and cache entries via the app instance.
    """
    logger.info(f"Attempting to delete full user profile for Telegram ID: {telegram_id}")
    try:
        user_settings_deleted, subscribed_user_deleted = await crud._delete_user_data_from_db(session, telegram_id)

        if not user_settings_deleted and not subscribed_user_deleted:
            logger.info(f"No DB data found for Telegram ID {telegram_id} to delete.")
        else:
            await session.commit()
            logger.debug(f"Committed DB deletions for {telegram_id}.")

        # Clear data from caches using the app instance
        # Assuming app has methods or directly manipulates its caches
        if telegram_id in app.user_settings_cache: # user_settings_cache is now part of app
            del app.user_settings_cache[telegram_id]
            logger.info(f"Removed user {telegram_id} from app.user_settings_cache.")

        app.subscribed_users_cache.discard(telegram_id)
        logger.info(f"User {telegram_id} discarded from app.subscribed_users_cache.")

        app.admin_ids_cache.discard(telegram_id) # Also remove from admin cache if they were an admin
        logger.info(f"User {telegram_id} discarded from app.admin_ids_cache (if present).")


        logger.info(f"Full user profile deletion process completed for Telegram ID: {telegram_id}. DB changes (if any) committed. Caches cleared via app instance.")
        return True

    except SQLAlchemyError as e_sql:
        await session.rollback()
        logger.error(f"SQLAlchemyError during full data deletion for {telegram_id}: {e_sql}. Rolling back.", exc_info=True)
        return False
    except Exception as e: # Catch other potential errors, e.g., if app object is malformed
        await session.rollback() # Rollback DB changes if any other error occurs mid-process
        logger.error(f"Unexpected error during full data deletion for {telegram_id}: {e}. Rolling back.", exc_info=True)
        return False
