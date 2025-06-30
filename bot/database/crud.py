import logging
import secrets
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, SQLModel

from bot.core.enums import DeeplinkAction
# Importing models from the new unified file
from bot.models import SubscribedUser, Admin, Deeplink, UserSettings
from bot.config import app_config # Changed from constants to app_config
from bot.state import SUBSCRIBED_USERS_CACHE, ADMIN_IDS_CACHE

logger = logging.getLogger(__name__)

async def db_add_generic(session: AsyncSession, model_instance: SQLModel) -> bool:
    try:
        session.add(model_instance)
        await session.commit()
        # For SQLModel, after commit, refresh is often needed to get DB-generated values if any,
        # or to ensure the instance is up-to-date with the session.
        await session.refresh(model_instance)
        logger.debug(f"Added record to {model_instance.__tablename__}: {model_instance}")
        return True
    except Exception as e:
        logger.error(f"Error adding to DB ({model_instance.__tablename__}): {e}", exc_info=True)
        await session.rollback()
        return False

async def db_remove_generic(session: AsyncSession, record_to_remove: SQLModel | None) -> bool:
    if record_to_remove:
        try:
            table_name = record_to_remove.__tablename__
            # Using SQLAlchemy's __mapper__ to access the primary key column(s).
            # This is a reliable and documented method.
            pk_col = record_to_remove.__mapper__.primary_key[0]
            pk_col_name = pk_col.name
            record_pk = getattr(record_to_remove, pk_col_name, 'N/A')

            await session.delete(record_to_remove)
            await session.commit()
            logger.debug(f"Removed record from {table_name} with PK ({pk_col_name}={record_pk})")
            return True
        except Exception as e:
            logger.error(f"Error removing from DB ({record_to_remove.__tablename__}): {e}", exc_info=True)
            await session.rollback()
            return False
    return False

async def _add_entity_if_not_exists(session: AsyncSession, model_class: type[SQLModel], telegram_id: int) -> bool:
    # For SQLModel, model_class will be like UserSettings, Admin, etc.
    # We assume telegram_id is the primary key for these models.
    existing_entity = await session.get(model_class, telegram_id)
    if existing_entity:
        logger.debug(f"User {telegram_id} already exists in {model_class.__tablename__}.")
        return False

    entity = model_class(telegram_id=telegram_id) # type: ignore
    return await db_add_generic(session, entity)


async def _remove_entity(session: AsyncSession, model_class: type[SQLModel], telegram_id: int) -> bool:
    entity = await session.get(model_class, telegram_id)
    if not entity:
        logger.debug(f"Entity with ID {telegram_id} not found in {model_class.__tablename__} for removal.")
        return False
    return await db_remove_generic(session, entity)


async def _get_all_entity_ids(session: AsyncSession, model_class: type[SQLModel]) -> list[int]:
    table_name = model_class.__tablename__
    try:
        # Assuming the PK column is named 'telegram_id' for these models.
        statement = select(model_class.telegram_id) # type: ignore
        result = await session.execute(statement)
        return result.scalars().all()
    except Exception as e:
        logger.error(f"Error getting all IDs from {table_name}: {e}", exc_info=True)
        return []

async def add_subscriber(session: AsyncSession, telegram_id: int) -> bool:
    added = await _add_entity_if_not_exists(session, SubscribedUser, telegram_id)
    if added:
        SUBSCRIBED_USERS_CACHE.add(telegram_id)
        logger.info(f"User {telegram_id} added to SUBSCRIBED_USERS_CACHE.")
    return added

async def remove_subscriber(session: AsyncSession, telegram_id: int) -> bool:
    removed = await _remove_entity(session, SubscribedUser, telegram_id)
    if removed:
        SUBSCRIBED_USERS_CACHE.discard(telegram_id)
        logger.info(f"User {telegram_id} removed from SUBSCRIBED_USERS_CACHE.")
    # Also remove user settings if they are being fully unsubscribed
    # This should ideally be part of a higher-level "unsubscribe" operation
    # For now, just removing from SubscribedUser table and cache.
    # Full data deletion is handled by delete_user_data_fully.
    return removed

async def get_all_subscribers_ids(session: AsyncSession) -> list[int]:
    return await _get_all_entity_ids(session, SubscribedUser)

async def add_admin(session: AsyncSession, telegram_id: int) -> bool:
    added = await _add_entity_if_not_exists(session, Admin, telegram_id)
    if added:
        ADMIN_IDS_CACHE.add(telegram_id)
        logger.info(f"Admin {telegram_id} added to ADMIN_IDS_CACHE.")
    return added

async def remove_admin_db(session: AsyncSession, telegram_id: int) -> bool:
    removed = await _remove_entity(session, Admin, telegram_id)
    if removed:
        ADMIN_IDS_CACHE.discard(telegram_id)
        logger.info(f"Admin {telegram_id} removed from ADMIN_IDS_CACHE.")
    return removed

async def get_all_admins_ids(session: AsyncSession) -> list[int]:
    return await _get_all_entity_ids(session, Admin)

async def create_deeplink(
    session: AsyncSession,
    action: DeeplinkAction,
    payload: str | None = None,
    expected_telegram_id: int | None = None
    # expiry_minutes parameter removed, will use app_config.DEEPLINK_TTL_SECONDS
) -> str:
    token_str = secrets.token_urlsafe(16)
    expiry_time = datetime.utcnow() + timedelta(seconds=app_config.DEEPLINK_TTL_SECONDS)
    deeplink_obj = Deeplink(
        token=token_str,
        action=action,
        payload=payload,
        expected_telegram_id=expected_telegram_id,
        expiry_time=expiry_time
    )
    if await db_add_generic(session, deeplink_obj):
        logger.debug(f"Created deeplink: token={token_str}, action={action}, payload={payload}, expected_id={expected_telegram_id}")
        return token_str
    # Consider raising a more specific error or handling it if db_add_generic returns False
    raise Exception(f"Failed to save deeplink for action {action}")


async def get_deeplink(session: AsyncSession, token: str) -> Deeplink | None:
    # session.get is simpler for PK lookups with SQLModel
    deeplink_obj = await session.get(Deeplink, token)
    if deeplink_obj:
        if deeplink_obj.expiry_time < datetime.utcnow():
            logger.warning(f"Deeplink {token} expired. Deleting.")
            # db_remove_generic expects the model instance itself
            await db_remove_generic(session, deeplink_obj)
            return None # Return None as it's expired and deleted
    return deeplink_obj

async def delete_deeplink_by_token(session: AsyncSession, token: str) -> bool:
    deeplink_obj = await session.get(Deeplink, token)
    if deeplink_obj:
        return await db_remove_generic(session, deeplink_obj)
    logger.debug(f"Deeplink {token} not found for deletion.")
    return False

async def delete_user_data_fully(session: AsyncSession, telegram_id: int) -> bool:
    """
    Deletes all data associated with a given telegram_id in a single transaction.
    Also removes the user from the in-memory cache upon successful deletion.
    """
    # Import here to avoid circular dependency at module load time
    from bot.core.user_settings import USER_SETTINGS_CACHE, remove_user_settings_from_cache

    logger.info(f"Attempting to delete all data for Telegram ID: {telegram_id}")
    try:
        user_settings_record = await session.get(UserSettings, telegram_id)
        subscribed_user_record = await session.get(SubscribedUser, telegram_id)
        # Potentially other related data in the future

        if not user_settings_record and not subscribed_user_record:
            logger.info(f"No data found for Telegram ID {telegram_id}. Nothing to delete.")
            # Ensure cache consistency even if no DB records were found
            remove_user_settings_from_cache(telegram_id)
            SUBSCRIBED_USERS_CACHE.discard(telegram_id)
            return True

        if user_settings_record:
            await session.delete(user_settings_record)
            logger.debug(f"Marked UserSettings for deletion for user {telegram_id}.")

        if subscribed_user_record:
            await session.delete(subscribed_user_record)
            logger.debug(f"Marked SubscribedUser for deletion for user {telegram_id}.")

        # Add deletion for other related data here if necessary

        await session.commit()

        # Clear from cache only after the transaction is successfully committed.
        remove_user_settings_from_cache(telegram_id) # Uses the new helper from user_settings.py
        SUBSCRIBED_USERS_CACHE.discard(telegram_id)
        logger.info(f"Successfully deleted all DB data for {telegram_id} and cleared from relevant caches.")
        return True

    except Exception as e:
        logger.error(f"Error during full data deletion for {telegram_id}: {e}. Rolling back.", exc_info=True)
        await session.rollback()
        return False
