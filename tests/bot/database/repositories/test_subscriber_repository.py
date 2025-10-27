from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.models import SubscribedUser
from bot.database.repositories.subscriber_repository import SubscriberRepository


@pytest.fixture(name="engine")
def engine_fixture() -> AsyncEngine:
    """Fixture for an in-memory SQLite engine."""
    return create_async_engine("sqlite+aiosqlite:///:memory:")


@pytest.fixture(name="session")
async def session_fixture(
    engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Fixture for an asynchronous session with a clean database."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine) as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest.fixture
def subscriber_repository(session: AsyncSession) -> SubscriberRepository:
    """Fixture for a SubscriberRepository instance."""
    return SubscriberRepository(session)


@pytest.mark.asyncio
async def test_add_subscriber(
    subscriber_repository: SubscriberRepository, session: AsyncSession
) -> None:
    """Test adding a new subscriber."""
    subscriber_id = 123
    subscriber = SubscribedUser(telegram_id=subscriber_id)
    await subscriber_repository.add(subscriber)
    await session.commit()

    retrieved_subscriber = await subscriber_repository.get_by_id(subscriber_id)
    assert retrieved_subscriber is not None
    assert retrieved_subscriber.telegram_id == subscriber_id


@pytest.mark.asyncio
async def test_get_subscriber_by_id(
    subscriber_repository: SubscriberRepository, session: AsyncSession
) -> None:
    """Test retrieving a subscriber by ID."""
    subscriber_id = 456
    subscriber = SubscribedUser(telegram_id=subscriber_id)
    session.add(subscriber)
    await session.commit()
    session.expunge_all()

    retrieved_subscriber = await subscriber_repository.get_by_id(subscriber_id)
    assert retrieved_subscriber is not None
    assert retrieved_subscriber.telegram_id == subscriber_id


@pytest.mark.asyncio
async def test_get_subscriber_by_id_not_found(
    subscriber_repository: SubscriberRepository,
) -> None:
    """Test retrieving a non-existent subscriber by ID."""
    retrieved_subscriber = await subscriber_repository.get_by_id(999)
    assert retrieved_subscriber is None


@pytest.mark.asyncio
async def test_get_all_subscribers(
    subscriber_repository: SubscriberRepository, session: AsyncSession
) -> None:
    """Test retrieving all subscribers."""
    subscriber1 = SubscribedUser(telegram_id=1)
    subscriber2 = SubscribedUser(telegram_id=2)
    session.add(subscriber1)
    session.add(subscriber2)
    await session.commit()
    session.expunge_all()

    all_subscribers = await subscriber_repository.get_all()
    assert len(all_subscribers) == 2
    assert {s.telegram_id for s in all_subscribers} == {1, 2}


@pytest.mark.asyncio
async def test_get_all_ids(
    subscriber_repository: SubscriberRepository, session: AsyncSession
) -> None:
    """Test retrieving all subscriber IDs."""
    subscriber1 = SubscribedUser(telegram_id=10)
    subscriber2 = SubscribedUser(telegram_id=20)
    session.add(subscriber1)
    session.add(subscriber2)
    await session.commit()
    session.expunge_all()

    all_ids = await subscriber_repository.get_all_ids()
    assert len(all_ids) == 2
    assert set(all_ids) == {10, 20}


@pytest.mark.asyncio
async def test_delete_subscriber(
    subscriber_repository: SubscriberRepository, session: AsyncSession
) -> None:
    """Test deleting a subscriber."""
    subscriber_id = 789
    subscriber = SubscribedUser(telegram_id=subscriber_id)
    session.add(subscriber)
    await session.commit()
    session.expunge_all()

    retrieved_subscriber = await subscriber_repository.get_by_id(subscriber_id)
    assert retrieved_subscriber is not None

    await subscriber_repository.delete(retrieved_subscriber)
    await session.commit()

    deleted_subscriber = await subscriber_repository.get_by_id(subscriber_id)
    assert deleted_subscriber is None
