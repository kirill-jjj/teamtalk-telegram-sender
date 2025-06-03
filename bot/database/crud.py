import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy import select, delete
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
        logger.info(f"Added record to {model_instance.__tablename__}: {model_instance}")
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
            logger.info(f"Removed record from {table_name} with PK {record_pk}")
            return True
        except Exception as e:
            logger.error(f"Error removing from DB ({record_to_remove.__tablename__}): {e}")
            await session.rollback()
            return False
    return False

async def add_subscriber(session: AsyncSession, telegram_id: int) -> bool:
    existing_subscriber = await session.get(SubscribedUser, telegram_id)
    if existing_subscriber:
        logger.warning(f"User {telegram_id} is already a subscriber.")
        return False # Indicate already exists, not an error
    subscriber = SubscribedUser(telegram_id=telegram_id)
    return await db_add_generic(session, subscriber)

async def remove_subscriber(session: AsyncSession, telegram_id: int) -> bool:
    subscriber = await session.get(SubscribedUser, telegram_id)
    if not subscriber:
        logger.warning(f"Subscriber with ID {telegram_id} not found for removal.")
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
        logger.warning(f"User {telegram_id} is already an admin.")
        return False
    admin = Admin(telegram_id=telegram_id)
    return await db_add_generic(session, admin)

async def remove_admin_db(session: AsyncSession, telegram_id: int) -> bool:
    admin = await session.get(Admin, telegram_id)
    if not admin:
        logger.warning(f"Admin with ID {telegram_id} not found for removal.")
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
        logger.info(f"Created deeplink: token={token_str}, action={action}, payload={payload}, expected_id={expected_telegram_id}")
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
    logger.warning(f"Deeplink {token} not found for deletion.")
    return False

# Note: UserSettings CRUD is mostly handled by core.user_settings for cache coherency.
# If direct UserSettings CRUD is needed outside that scope, it can be added here.
async def get_user_settings_row(session: AsyncSession, telegram_id: int) -> UserSettings | None:
    """Directly fetches UserSettings row from DB, bypassing cache."""
    return await session.get(UserSettings, telegram_id)

async def delete_user_data_fully(session: AsyncSession, telegram_id: int) -> bool:
    """
    Deletes all data associated with a given telegram_id.
    This includes UserSettings and SubscribedUser records.
    """
    logger.info(f"Attempting to delete all data for Telegram ID: {telegram_id}")
    settings_deleted_successfully = False
    subscriber_removed_successfully = False

    # 1. Delete UserSettings
    user_settings_record = await session.get(UserSettings, telegram_id)
    if user_settings_record:
        logger.info(f"Found UserSettings for {telegram_id}. Proceeding with deletion.")
        settings_deleted_successfully = await db_remove_generic(session, user_settings_record)
        if settings_deleted_successfully:
            logger.info(f"Successfully deleted UserSettings for {telegram_id}.")
        else:
            logger.error(f"Failed to delete UserSettings for {telegram_id}.")
    else:
        logger.info(f"No UserSettings found for {telegram_id}. Skipping UserSettings deletion.")
        settings_deleted_successfully = True # Considered successful as there's nothing to delete

    # 2. Remove Subscriber
    # remove_subscriber already handles logging and non-existence appropriately.
    # It returns True if removed, False if not found or error during delete.
    # We need to distinguish "not found" from "error during delete" for overall success.

    # Check if subscriber exists before attempting removal to refine success logic
    subscriber_exists = await session.get(SubscribedUser, telegram_id)
    if subscriber_exists:
        subscriber_removed_successfully = await db_remove_generic(session, subscriber_exists)
        if subscriber_removed_successfully:
            logger.info(f"Successfully removed SubscribedUser for {telegram_id}.")
        else:
            logger.error(f"Error removing SubscribedUser for {telegram_id} during db_remove_generic call.")
    else:
        logger.info(f"No SubscribedUser record found for {telegram_id}. Skipping SubscribedUser deletion.")
        subscriber_removed_successfully = True # Considered successful as there's nothing to delete

    overall_success = settings_deleted_successfully and subscriber_removed_successfully
    if overall_success:
        logger.info(f"Successfully completed full data deletion process for Telegram ID: {telegram_id}.")
    else:
        logger.error(f"Full data deletion process for Telegram ID: {telegram_id} encountered issues. Settings deleted: {settings_deleted_successfully}, Subscriber part: {subscriber_removed_successfully}")
    return overall_success
