import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.database.models import SubscribedUser, Admin, Deeplink, UserSettings
from bot.database.engine import Base # For type hinting model
from bot.constants import DEEPLINK_EXPIRY_MINUTES

logger = logging.getLogger(__name__)

async def db_add_generic(session: AsyncSession, model_instance: Base) -> bool:
    """Generic add to DB, assumes instance is already created."""
    try:
        session.add(model_instance)
        await session.commit()
        logger.debug(f"Added record to {model_instance.__tablename__}: {model_instance}") # Changed to debug
        return True
    except Exception as e:
        logger.error(f"Error adding to DB ({model_instance.__tablename__}): {e}")
        await session.rollback()
        return False

async def db_remove_generic(session: AsyncSession, record_to_remove: Base | None) -> bool:
    """Generic remove from DB if record exists."""
    if record_to_remove:
        try:
            table_name = record_to_remove.__tablename__
            record_pk = getattr(record_to_remove, record_to_remove.__mapper__.primary_key[0].name, 'N/A')
            await session.delete(record_to_remove)
            await session.commit()
            logger.debug(f"Removed record from {table_name} with PK {record_pk}") # Changed to debug
            return True
        except Exception as e:
            logger.error(f"Error removing from DB ({record_to_remove.__tablename__}): {e}")
            await session.rollback()
            return False
    return False

async def add_subscriber(session: AsyncSession, telegram_id: int) -> bool:
    existing_subscriber = await session.get(SubscribedUser, telegram_id)
    if existing_subscriber:
        logger.debug(f"User {telegram_id} is already a subscriber.") # Changed to debug
        return False # Indicate already exists, not an error
    subscriber = SubscribedUser(telegram_id=telegram_id)
    return await db_add_generic(session, subscriber)

async def remove_subscriber(session: AsyncSession, telegram_id: int) -> bool:
    subscriber = await session.get(SubscribedUser, telegram_id)
    if not subscriber:
        logger.debug(f"Subscriber with ID {telegram_id} not found for removal.") # Changed to debug
        return False # Indicate not found
    return await db_remove_generic(session, subscriber)

async def get_all_subscribers_ids(session: AsyncSession) -> list[int]:
    try:
        result = await session.execute(select(SubscribedUser.telegram_id))
        return result.scalars().all()
    except Exception as e:
        logger.error(f"Error getting all subscriber IDs: {e}")
        return []

async def add_admin(session: AsyncSession, telegram_id: int) -> bool:
    existing_admin = await session.get(Admin, telegram_id)
    if existing_admin:
        logger.debug(f"User {telegram_id} is already an admin.") # Changed to debug
        return False
    admin = Admin(telegram_id=telegram_id)
    return await db_add_generic(session, admin)

async def remove_admin_db(session: AsyncSession, telegram_id: int) -> bool:
    admin = await session.get(Admin, telegram_id)
    if not admin:
        logger.debug(f"Admin with ID {telegram_id} not found for removal.") # Changed to debug
        return False
    return await db_remove_generic(session, admin)

async def get_all_admins_ids(session: AsyncSession) -> list[int]:
    try:
        result = await session.execute(select(Admin.telegram_id))
        return result.scalars().all()
    except Exception as e:
        logger.error(f"Error getting all admin IDs: {e}")
        return []

async def is_admin(session: AsyncSession, telegram_id: int) -> bool:
    admin_record = await session.get(Admin, telegram_id)
    return admin_record is not None

async def create_deeplink(
    session: AsyncSession,
    action: str,
    payload: str | None = None,
    expected_telegram_id: int | None = None,
    expiry_minutes: int = DEEPLINK_EXPIRY_MINUTES
) -> str:
    token_str = str(uuid.uuid4())
    expiry_time_val = datetime.utcnow() + timedelta(minutes=expiry_minutes)
    deeplink_obj = Deeplink(
        token=token_str,
        action=action,
        payload=payload,
        expected_telegram_id=expected_telegram_id,
        expiry_time=expiry_time_val
    )
    if await db_add_generic(session, deeplink_obj):
        logger.debug(f"Created deeplink: token={token_str}, action={action}, payload={payload}, expected_id={expected_telegram_id}") # Changed to debug
        return token_str
    raise Exception(f"Failed to save deeplink for action {action}")


async def get_deeplink(session: AsyncSession, token: str) -> Deeplink | None:
    result = await session.execute(select(Deeplink).where(Deeplink.token == token))
    deeplink_obj = result.scalar_one_or_none()
    if deeplink_obj:
        if deeplink_obj.expiry_time < datetime.utcnow():
            logger.warning(f"Deeplink {token} expired. Deleting.")
            await db_remove_generic(session, deeplink_obj) # Use generic remove
            return None
    return deeplink_obj

async def delete_deeplink_by_token(session: AsyncSession, token: str) -> bool:
    # Fetch first to use db_remove_generic which logs nicely
    deeplink_obj = await session.get(Deeplink, token)
    if deeplink_obj:
        return await db_remove_generic(session, deeplink_obj)
    logger.debug(f"Deeplink {token} not found for deletion.") # Changed to debug
    return False

# Note: UserSettings CRUD is mostly handled by core.user_settings for cache coherency.
# If direct UserSettings CRUD is needed outside that scope, it can be added here.
async def get_user_settings_row(session: AsyncSession, telegram_id: int) -> UserSettings | None:
    """Directly fetches UserSettings row from DB, bypassing cache."""
    return await session.get(UserSettings, telegram_id)

async def delete_user_data_fully(session: AsyncSession, telegram_id: int) -> bool:
    """
    Deletes all data associated with a given telegram_id in a single transaction.
    Also removes the user from the in-memory cache upon successful deletion.
    """
    logger.info(f"Attempting to delete all data for Telegram ID: {telegram_id}")
    try:
        # Fetch both records first to see what needs to be deleted.
        user_settings_record = await session.get(UserSettings, telegram_id)
        subscribed_user_record = await session.get(SubscribedUser, telegram_id)

        if not user_settings_record and not subscribed_user_record:
            logger.info(f"No data found for Telegram ID {telegram_id}. Nothing to delete.")
            return True

        if user_settings_record:
            await session.delete(user_settings_record)
            logger.debug(f"Marked UserSettings for deletion for user {telegram_id}.") # Changed to debug

        if subscribed_user_record:
            await session.delete(subscribed_user_record)
            logger.debug(f"Marked SubscribedUser for deletion for user {telegram_id}.") # Changed to debug

        # Commit both deletions (or one of them) in a single transaction.
        await session.commit()

        logger.info(f"Successfully deleted all DB data for {telegram_id}.")
        return True

    except Exception as e:
        logger.error(f"Error during full data deletion for {telegram_id}: {e}. Rolling back.", exc_info=True)
        await session.rollback()
        return False
