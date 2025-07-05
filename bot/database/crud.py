import logging
import secrets
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, SQLModel

from bot.core.enums import DeeplinkAction
from bot.models import SubscribedUser, Admin, Deeplink, UserSettings, BanList
from bot.constants import DEEPLINK_TOKEN_LENGTH_BYTES

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
    except SQLAlchemyError as e:
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
        except SQLAlchemyError as e:
            logger.error(f"Error removing from DB ({record_to_remove.__tablename__}): {e}", exc_info=True)
            await session.rollback()
            return False
    return False

async def _add_entity_if_not_exists(session: AsyncSession, model_class: type[SQLModel], telegram_id: int) -> bool:
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
        statement = select(model_class.telegram_id) # type: ignore
        result = await session.execute(statement)
        return result.scalars().all()
    except SQLAlchemyError as e:
        logger.error(f"Error getting all IDs from {table_name}: {e}", exc_info=True)
        return []

async def add_subscriber(session: AsyncSession, telegram_id: int) -> bool:
    return await _add_entity_if_not_exists(session, SubscribedUser, telegram_id)

async def get_all_subscribers_ids(session: AsyncSession) -> list[int]:
    return await _get_all_entity_ids(session, SubscribedUser)

async def add_admin(session: AsyncSession, telegram_id: int) -> bool:
    return await _add_entity_if_not_exists(session, Admin, telegram_id)

async def remove_admin_db(session: AsyncSession, telegram_id: int) -> bool:
    return await _remove_entity(session, Admin, telegram_id)

async def get_all_admins_ids(session: AsyncSession) -> list[int]:
    return await _get_all_entity_ids(session, Admin)

async def create_deeplink(
    session: AsyncSession,
    action: DeeplinkAction,
    deeplink_ttl_seconds: int,
    payload: str | None = None,
    expected_telegram_id: int | None = None
) -> str | None:
    token_str = secrets.token_urlsafe(DEEPLINK_TOKEN_LENGTH_BYTES)
    expiry_time = datetime.utcnow() + timedelta(seconds=deeplink_ttl_seconds)
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
    else:
        logger.error(f"Failed to save deeplink to DB for action {action}.")
        return None


async def get_deeplink(session: AsyncSession, token: str) -> Deeplink | None:
    deeplink_obj = await session.get(Deeplink, token)
    if deeplink_obj:
        if deeplink_obj.expiry_time < datetime.utcnow():
            logger.warning(f"Deeplink {token} expired. Deleting.")
            await db_remove_generic(session, deeplink_obj)
            return None
    return deeplink_obj

async def delete_deeplink_by_token(session: AsyncSession, token: str) -> bool:
    deeplink_obj = await session.get(Deeplink, token)
    if deeplink_obj:
        return await db_remove_generic(session, deeplink_obj)
    logger.debug(f"Deeplink {token} not found for deletion.")
    return False

async def _delete_user_data_from_db(session: AsyncSession, telegram_id: int) -> tuple[bool, bool]:
    """
    Deletes UserSettings (and related MutedUser) and SubscribedUser records from the database.
    Does NOT commit the session.
    Returns a tuple of booleans: (user_settings_deleted, subscribed_user_deleted)
    """
    logger.info(f"Attempting to delete DB data for Telegram ID: {telegram_id}")

    user_settings_deleted = False
    subscribed_user_deleted = False

    user_settings_record = await session.get(UserSettings, telegram_id)
    if user_settings_record:
        await session.delete(user_settings_record)
        user_settings_deleted = True
        logger.debug(f"Marked UserSettings for deletion for user {telegram_id}.")

    subscribed_user_record = await session.get(SubscribedUser, telegram_id)
    if subscribed_user_record:
        await session.delete(subscribed_user_record)
        subscribed_user_deleted = True
        logger.debug(f"Marked SubscribedUser for deletion for user {telegram_id}.")

    return user_settings_deleted, subscribed_user_deleted


# --- BanList CRUD Functions ---

async def add_to_ban_list(
    session: AsyncSession,
    telegram_id: int | None = None,
    teamtalk_username: str | None = None,
    reason: str | None = None
) -> bool:
    if not telegram_id and not teamtalk_username:
        logger.error("Attempted to add to ban list without telegram_id or teamtalk_username.")
        return False

    ban_entry = BanList(
        telegram_id=telegram_id,
        teamtalk_username=teamtalk_username,
        ban_reason=reason
    )
    added = await db_add_generic(session, ban_entry)
    if added:
        logger.info(f"Added to ban list: telegram_id={telegram_id}, teamtalk_username='{teamtalk_username}', reason='{reason}'")
    return added

async def remove_from_ban_list_by_id(session: AsyncSession, ban_id: int) -> bool:
    ban_entry = await session.get(BanList, ban_id)
    removed = await db_remove_generic(session, ban_entry)
    if removed:
        logger.info(f"Removed from ban list by id: {ban_id}")
    return removed

async def is_telegram_id_banned(session: AsyncSession, telegram_id: int) -> bool:
    statement = select(BanList).where(BanList.telegram_id == telegram_id)
    result = await session.execute(statement)
    return result.scalars().first() is not None

async def is_teamtalk_username_banned(session: AsyncSession, teamtalk_username: str) -> bool:
    statement = select(BanList).where(BanList.teamtalk_username == teamtalk_username)
    result = await session.execute(statement)
    return result.scalars().first() is not None

async def get_ban_entries_for_telegram_id(session: AsyncSession, telegram_id: int) -> list[BanList]:
    statement = select(BanList).where(BanList.telegram_id == telegram_id)
    result = await session.execute(statement)
    return result.scalars().all()

async def get_ban_entries_for_teamtalk_username(session: AsyncSession, teamtalk_username: str) -> list[BanList]:
    statement = select(BanList).where(BanList.teamtalk_username == teamtalk_username)
    result = await session.execute(statement)
    return result.scalars().all()
