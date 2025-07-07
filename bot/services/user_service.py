import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import crud

if TYPE_CHECKING:
    from bot.services_container import Services  # Import Services

logger = logging.getLogger(__name__)


async def delete_full_user_profile(
    session: AsyncSession,
    telegram_id: int,
    services: "Services",  # Changed from app: "Application"
) -> bool:
    """Orchestrates the full deletion of a user's profile,
    including database records and cache entries via the services container.
    """
    logger.info(f"Attempting to delete full user profile for Telegram ID: {telegram_id}")
    try:
        user_settings_deleted, subscribed_user_deleted = await crud._delete_user_data_from_db(session, telegram_id)

        if not user_settings_deleted and not subscribed_user_deleted:
            logger.info(f"No DB data found for Telegram ID {telegram_id} to delete.")
        else:
            await session.commit()
            logger.debug(f"Committed DB deletions for {telegram_id}.")

        # Clear data from caches using the services container
        if telegram_id in services.user_settings_cache:
            del services.user_settings_cache[telegram_id]
            logger.info(f"Removed user {telegram_id} from services.user_settings_cache.")

        services.subscribed_users_cache.discard(telegram_id)
        logger.info(f"User {telegram_id} discarded from services.subscribed_users_cache.")

        services.admin_ids_cache.discard(telegram_id)  # Also remove from admin cache if they were an admin
        logger.info(f"User {telegram_id} discarded from services.admin_ids_cache (if present).")

        logger.info(
            f"Full user profile deletion process completed for Telegram ID: {telegram_id}. "
            f"DB changes (if any) committed. Caches cleared via services container."
        )
        return True

    except SQLAlchemyError as e_sql:
        await session.rollback()
        logger.error(
            f"SQLAlchemyError during full data deletion for {telegram_id}: {e_sql}. Rolling back.", exc_info=True
        )
        return False
    except Exception as e:
        await session.rollback()
        logger.error(f"Unexpected error during full data deletion for {telegram_id}: {e}. Rolling back.", exc_info=True)
        return False
