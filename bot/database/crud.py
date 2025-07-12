"""Database CRUD (Create, Read, Update, Delete) operations."""

import datetime as dt
from datetime import datetime, timedelta
import logging
import secrets
from typing import TypeVar

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.constants import DEEPLINK_TOKEN_LENGTH_BYTES
from bot.core.enums import DeeplinkAction
from bot.models import Admin, BanList, Deeplink, SubscribedUser, UserSettings

logger = logging.getLogger(__name__)

__all__ = [
    "Admin",
    "add_admin",
    "add_subscriber",
    "add_to_ban_list",
    "create_deeplink",
    "db_add_generic",
    "db_remove_generic",
    "delete_deeplink_by_token",
    "get_all_admins_ids",
    "get_all_banned_users",
    "get_all_subscribers_ids",
    "get_ban_entries_for_teamtalk_username",
    "get_ban_entries_for_telegram_id",
    "get_deeplink",
    "is_teamtalk_username_banned",
    "is_telegram_id_banned",
    "remove_admin_db",
    "remove_ban_entries_for_telegram_id",
    "remove_from_ban_list_by_id",
]

T = TypeVar("T", bound=SQLModel)


async def db_add_generic(session: AsyncSession, model_instance: T) -> bool:
    """Adds a generic SQLModel instance to the database and commits.

    Args:
        session: The active AsyncSession.
        model_instance: The SQLModel instance to add.

    Returns:
        True if successful, False otherwise.
    """
    try:
        session.add(model_instance)
        await session.commit()
        # For SQLModel, after commit, refresh is often needed to get DB-generated values if any,
        # or to ensure the instance is up-to-date with the session.
        await session.refresh(model_instance)
        logger.debug("Added record to %s: %s", model_instance.__tablename__, model_instance)
    except SQLAlchemyError:
        logger.exception("Error adding to DB (%s).", model_instance.__tablename__)
        await session.rollback()
        return False
    else:
        return True


async def db_remove_generic(session: AsyncSession, record_to_remove: T | None) -> bool:
    """Removes a generic SQLModel instance from the database and commits.

    Args:
        session: The active AsyncSession.
        record_to_remove: The SQLModel instance to remove. Can be None.

    Returns:
        True if successful or if record_to_remove was None, False on error.
    """
    if record_to_remove:
        try:
            table_name = record_to_remove.__tablename__
            # Using SQLAlchemy's __mapper__ to access the primary key column(s).
            # This is a reliable and documented method.
            # Mypy struggles with __mapper__ on TypeVar T bound to SQLModel.
            pk_col = record_to_remove.__mapper__.primary_key[0]  # type: ignore[attr-defined]
            pk_col_name = pk_col.name
            record_pk = getattr(record_to_remove, pk_col_name, "N/A")

            await session.delete(record_to_remove)
            await session.commit()
            logger.debug("Removed record from %s with PK (%s=%s)", table_name, pk_col_name, record_pk)
        except SQLAlchemyError:
            logger.exception("Error removing from DB (%s).", record_to_remove.__tablename__)
            await session.rollback()
            return False
        else:
            return True
    return False


async def _add_entity_if_not_exists(session: AsyncSession, model_class: type[T], telegram_id: int) -> bool:
    existing_entity = await session.get(model_class, telegram_id)
    if existing_entity:
        logger.debug("User %s already exists in %s.", telegram_id, model_class.__tablename__)
        return False

    entity = model_class(telegram_id=telegram_id)
    return await db_add_generic(session, entity)


async def _remove_entity(session: AsyncSession, model_class: type[T], telegram_id: int) -> bool:
    entity = await session.get(model_class, telegram_id)
    if not entity:
        logger.debug("Entity with ID %s not found in %s for removal.", telegram_id, model_class.__tablename__)
        return False
    return await db_remove_generic(session, entity)


async def _get_all_entity_ids(session: AsyncSession, model_class: type[T]) -> list[int]:
    table_name = model_class.__tablename__
    try:
        # Assuming all models used with this function have 'telegram_id'
        statement = select(model_class.telegram_id)  # type: ignore[attr-defined]
        result = await session.exec(statement)
        return list(result.all())
    except SQLAlchemyError:
        logger.exception("Error getting all IDs from %s.", table_name)
        return []


async def add_subscriber(session: AsyncSession, telegram_id: int) -> bool:
    """Adds a new subscriber if they don't already exist."""
    return await _add_entity_if_not_exists(session, SubscribedUser, telegram_id)


async def get_all_subscribers_ids(session: AsyncSession) -> list[int]:
    """Gets a list of all subscriber Telegram IDs."""
    return await _get_all_entity_ids(session, SubscribedUser)


async def add_admin(session: AsyncSession, telegram_id: int) -> bool:
    """Adds a new admin if they don't already exist."""
    return await _add_entity_if_not_exists(session, Admin, telegram_id)


async def remove_admin_db(session: AsyncSession, telegram_id: int) -> bool:
    """Removes an admin by their Telegram ID."""
    return await _remove_entity(session, Admin, telegram_id)


async def get_all_admins_ids(session: AsyncSession) -> list[int]:
    """Gets a list of all admin Telegram IDs."""
    return await _get_all_entity_ids(session, Admin)


async def create_deeplink(
    session: AsyncSession,
    action: DeeplinkAction,
    deeplink_ttl_seconds: int,
    payload: str | None = None,
    expected_telegram_id: int | None = None,
) -> str | None:
    """Creates a new deeplink token and stores it in the database.

    Args:
        session: The active AsyncSession.
        action: The DeeplinkAction to perform.
        deeplink_ttl_seconds: Time-to-live for the deeplink in seconds.
        payload: Optional payload associated with the deeplink.
        expected_telegram_id: Optional Telegram ID expected to use this deeplink.

    Returns:
        The generated token string if successful, None otherwise.
    """
    token_str = secrets.token_urlsafe(DEEPLINK_TOKEN_LENGTH_BYTES)
    expiry_time = datetime.now(dt.UTC) + timedelta(seconds=deeplink_ttl_seconds)
    deeplink_obj = Deeplink(
        token=token_str,
        action=action,
        payload=payload,
        expected_telegram_id=expected_telegram_id,
        expiry_time=expiry_time,
    )
    if await db_add_generic(session, deeplink_obj):
        logger.debug(
            "Created deeplink: token=%s, action=%s, payload=%s, expected_id=%s",
            token_str,
            action,
            payload,
            expected_telegram_id,
        )
        return token_str
    logger.error("Failed to save deeplink to DB for action %s.", action)
    return None


async def get_deeplink(session: AsyncSession, token: str) -> Deeplink | None:
    """Retrieves a deeplink by its token, deleting it if expired.

    Args:
        session: The active AsyncSession.
        token: The deeplink token string.

    Returns:
        The Deeplink object if found and not expired, None otherwise.
    """
    deeplink_obj = await session.get(Deeplink, token)
    if deeplink_obj:
        # Assume expiry_time from DB is naive but represents UTC. Make it aware.
        loaded_expiry_time_utc = deeplink_obj.expiry_time.replace(tzinfo=dt.UTC)
        if loaded_expiry_time_utc < datetime.now(dt.UTC):
            logger.warning("Deeplink %s expired. Deleting.", token)
            await db_remove_generic(session, deeplink_obj)
            return None
    return deeplink_obj


async def delete_deeplink_by_token(session: AsyncSession, token: str) -> bool:
    """Deletes a deeplink from the database by its token.

    Args:
        session: The active AsyncSession.
        token: The token of the deeplink to delete.

    Returns:
        True if the deeplink was found and deleted, False otherwise.
    """
    deeplink_obj = await session.get(Deeplink, token)
    if deeplink_obj:
        return await db_remove_generic(session, deeplink_obj)
    logger.debug("Deeplink %s not found for deletion.", token)
    return False


async def _delete_user_data_from_db(session: AsyncSession, telegram_id: int) -> tuple[bool, bool]:
    """Deletes UserSettings (and related MutedUser) and SubscribedUser records.

    Does NOT commit the session.

    Args:
        session: The active AsyncSession.
        telegram_id: The Telegram ID of the user whose data is to be deleted.

    Returns:
        A tuple (user_settings_deleted, subscribed_user_deleted), where each
        boolean indicates if the respective record type was found and marked for deletion.
    """
    logger.info("Attempting to delete DB data for Telegram ID: %s", telegram_id)

    user_settings_deleted = False
    subscribed_user_deleted = False

    user_settings_record = await session.get(UserSettings, telegram_id)
    if user_settings_record:
        await session.delete(user_settings_record)
        user_settings_deleted = True
        logger.debug("Marked UserSettings for deletion for user %s.", telegram_id)

    subscribed_user_record = await session.get(SubscribedUser, telegram_id)
    if subscribed_user_record:
        await session.delete(subscribed_user_record)
        subscribed_user_deleted = True
        logger.debug("Marked SubscribedUser for deletion for user %s.", telegram_id)

    return user_settings_deleted, subscribed_user_deleted


# --- BanList CRUD Functions ---


async def add_to_ban_list(
    session: AsyncSession,
    telegram_id: int | None = None,
    teamtalk_username: str | None = None,
    reason: str | None = None,
) -> bool:
    """Adds an entry to the ban list.

    At least one of telegram_id or teamtalk_username must be provided.

    Args:
        session: The active AsyncSession.
        telegram_id: Optional Telegram ID to ban.
        teamtalk_username: Optional TeamTalk username to ban.
        reason: Optional reason for the ban.

    Returns:
        True if the entry was successfully added, False otherwise.
    """
    if not telegram_id and not teamtalk_username:
        logger.error("Attempted to add to ban list without telegram_id or teamtalk_username.")
        return False

    ban_entry = BanList(telegram_id=telegram_id, teamtalk_username=teamtalk_username, ban_reason=reason)
    added = await db_add_generic(session, ban_entry)
    if added:
        logger.info(
            "Added to ban list: telegram_id=%s, teamtalk_username='%s', reason='%s'",
            telegram_id,
            teamtalk_username,
            reason,
        )
    return added


async def remove_from_ban_list_by_id(session: AsyncSession, ban_id: int) -> bool:
    """Removes a ban list entry by its primary ID."""
    ban_entry = await session.get(BanList, ban_id)
    removed = await db_remove_generic(session, ban_entry)
    if removed:
        logger.info("Removed from ban list by id: %s", ban_id)
    return removed


async def is_telegram_id_banned(session: AsyncSession, telegram_id: int) -> bool:
    """Checks if a Telegram ID is present in the ban list."""
    statement = select(BanList).where(BanList.telegram_id == telegram_id)
    result = await session.exec(statement)
    return result.first() is not None


async def is_teamtalk_username_banned(session: AsyncSession, teamtalk_username: str) -> bool:
    """Checks if a TeamTalk username is present in the ban list."""
    statement = select(BanList).where(BanList.teamtalk_username == teamtalk_username)
    result = await session.exec(statement)
    return result.first() is not None


async def get_ban_entries_for_telegram_id(session: AsyncSession, telegram_id: int) -> list[BanList]:
    """Retrieves all ban list entries associated with a Telegram ID."""
    statement = select(BanList).where(BanList.telegram_id == telegram_id)
    result = await session.exec(statement)
    return list(result.all())


async def get_ban_entries_for_teamtalk_username(session: AsyncSession, teamtalk_username: str) -> list[BanList]:
    """Retrieves all ban list entries associated with a TeamTalk username."""
    statement = select(BanList).where(BanList.teamtalk_username == teamtalk_username)
    result = await session.exec(statement)
    return list(result.all())


async def get_all_banned_users(session: AsyncSession) -> list[BanList]:
    """Retrieves all entries from the ban list."""
    statement = select(BanList)
    result = await session.exec(statement)
    return list(result.all())


async def remove_ban_entries_for_telegram_id(session: AsyncSession, telegram_id: int) -> bool:
    """Removes all ban entries for a given Telegram ID and associated TeamTalk usernames."""
    try:
        # First, find all entries for the given telegram_id to identify associated tt_usernames
        user_settings = await session.get(UserSettings, telegram_id)
        tt_username = user_settings.teamtalk_username if user_settings else None

        # Collect all entries to be deleted
        entries_to_delete = []

        # Get bans by telegram_id
        tg_ban_entries = await get_ban_entries_for_telegram_id(session, telegram_id)
        entries_to_delete.extend(tg_ban_entries)

        # Get bans by associated tt_username
        if tt_username:
            tt_ban_entries = await get_ban_entries_for_teamtalk_username(session, tt_username)
            entries_to_delete.extend(tt_ban_entries)

        if not entries_to_delete:
            logger.info("No ban entries found for Telegram ID %s to remove.", telegram_id)
            return True # No entries to delete is considered a success

        for entry in set(entries_to_delete): # Use set to avoid duplicates
            await session.delete(entry)

        await session.commit()
        logger.info("Successfully removed all ban entries for Telegram ID %s.", telegram_id)
    except SQLAlchemyError:
        await session.rollback()
        logger.exception("Failed to remove ban entries for Telegram ID %s.", telegram_id)
        return False
    else:
        return True
