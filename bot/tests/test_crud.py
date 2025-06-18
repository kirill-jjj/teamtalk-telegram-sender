import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from bot.database.models import Base, SubscribedUser, Admin
from bot.database.crud import (
    add_subscriber,
    remove_subscriber,
    get_all_subscribers_ids,
    add_admin,
    remove_admin_db,
    get_all_admins_ids,
    is_admin
)

# Use an in-memory SQLite database for testing
DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="function") # Changed from session to function for better isolation
async def async_engine():
    engine = create_async_engine(DATABASE_URL, echo=False) # Disable echo for cleaner test output
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="function") # Changed from session to function
async def db_session(async_engine):
    async_session_maker = sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_maker() as session:
        yield session
        await session.rollback() # Ensure no changes leak between tests

@pytest.mark.asyncio
async def test_add_and_get_subscriber(db_session: AsyncSession):
    test_user_id = 12345
    assert await get_all_subscribers_ids(db_session) == []

    added = await add_subscriber(db_session, test_user_id)
    assert added is True

    subscribers = await get_all_subscribers_ids(db_session)
    assert subscribers == [test_user_id]

    # Try adding the same subscriber again
    added_again = await add_subscriber(db_session, test_user_id)
    assert added_again is False # Should indicate already exists

    subscribers_after_reattempt = await get_all_subscribers_ids(db_session)
    assert subscribers_after_reattempt == [test_user_id] # Should still be one

@pytest.mark.asyncio
async def test_remove_subscriber(db_session: AsyncSession):
    test_user_id = 67890
    await add_subscriber(db_session, test_user_id)
    assert await get_all_subscribers_ids(db_session) == [test_user_id]

    removed = await remove_subscriber(db_session, test_user_id)
    assert removed is True
    assert await get_all_subscribers_ids(db_session) == []

    # Try removing a non-existent subscriber
    removed_again = await remove_subscriber(db_session, test_user_id)
    assert removed_again is False

@pytest.mark.asyncio
async def test_add_and_get_admin(db_session: AsyncSession):
    test_admin_id = 11122
    assert await get_all_admins_ids(db_session) == []
    assert await is_admin(db_session, test_admin_id) is False

    added = await add_admin(db_session, test_admin_id)
    assert added is True
    assert await is_admin(db_session, test_admin_id) is True

    admins = await get_all_admins_ids(db_session)
    assert admins == [test_admin_id]

    added_again = await add_admin(db_session, test_admin_id)
    assert added_again is False # Should indicate already exists

@pytest.mark.asyncio
async def test_remove_admin(db_session: AsyncSession):
    test_admin_id = 33445
    await add_admin(db_session, test_admin_id)
    assert await get_all_admins_ids(db_session) == [test_admin_id]
    assert await is_admin(db_session, test_admin_id) is True

    removed = await remove_admin_db(db_session, test_admin_id)
    assert removed is True
    assert await get_all_admins_ids(db_session) == []
    assert await is_admin(db_session, test_admin_id) is False

    removed_again = await remove_admin_db(db_session, test_admin_id)
    assert removed_again is False

@pytest.mark.asyncio
async def test_get_empty_subscribers(db_session: AsyncSession):
    assert await get_all_subscribers_ids(db_session) == []

@pytest.mark.asyncio
async def test_get_empty_admins(db_session: AsyncSession):
    assert await get_all_admins_ids(db_session) == []
