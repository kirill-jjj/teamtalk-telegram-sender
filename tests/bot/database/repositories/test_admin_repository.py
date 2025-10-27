"""Tests for the AdminRepository."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.models import Admin
from bot.database.repositories.admin_repository import AdminRepository


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
def admin_repository(session: AsyncSession) -> AdminRepository:
    """Fixture for an AdminRepository instance."""
    return AdminRepository(session)


@pytest.mark.asyncio
async def test_add_admin(
    admin_repository: AdminRepository, session: AsyncSession
) -> None:
    """Test adding a new admin."""
    admin_id = 123
    admin = Admin(telegram_id=admin_id)
    await admin_repository.add(admin)
    await session.commit()

    retrieved_admin = await admin_repository.get_by_id(admin_id)
    assert retrieved_admin is not None
    assert retrieved_admin.telegram_id == admin_id


@pytest.mark.asyncio
async def test_get_admin_by_id(
    admin_repository: AdminRepository, session: AsyncSession
) -> None:
    """Test retrieving an admin by ID."""
    admin_id = 456
    admin = Admin(telegram_id=admin_id)
    session.add(admin)
    await session.commit()
    session.expunge_all()  # Clear session to ensure data is fetched from DB

    retrieved_admin = await admin_repository.get_by_id(admin_id)
    assert retrieved_admin is not None
    assert retrieved_admin.telegram_id == admin_id


@pytest.mark.asyncio
async def test_get_admin_by_id_not_found(admin_repository: AdminRepository) -> None:
    """Test retrieving a non-existent admin by ID."""
    retrieved_admin = await admin_repository.get_by_id(999)
    assert retrieved_admin is None


@pytest.mark.asyncio
async def test_get_all_admins(
    admin_repository: AdminRepository, session: AsyncSession
) -> None:
    """Test retrieving all admins."""
    admin1 = Admin(telegram_id=1)
    admin2 = Admin(telegram_id=2)
    session.add(admin1)
    session.add(admin2)
    await session.commit()
    session.expunge_all()

    all_admins = await admin_repository.get_all()
    assert len(all_admins) == 2
    assert {a.telegram_id for a in all_admins} == {1, 2}


@pytest.mark.asyncio
async def test_get_all_ids(
    admin_repository: AdminRepository, session: AsyncSession
) -> None:
    """Test retrieving all admin IDs."""
    admin1 = Admin(telegram_id=10)
    admin2 = Admin(telegram_id=20)
    session.add(admin1)
    session.add(admin2)
    await session.commit()
    session.expunge_all()

    all_ids = await admin_repository.get_all_ids()
    assert len(all_ids) == 2
    assert set(all_ids) == {10, 20}


@pytest.mark.asyncio
async def test_delete_admin(
    admin_repository: AdminRepository, session: AsyncSession
) -> None:
    """Test deleting an admin."""
    admin_id = 789
    admin = Admin(telegram_id=admin_id)
    session.add(admin)
    await session.commit()
    session.expunge_all()

    retrieved_admin = await admin_repository.get_by_id(admin_id)
    assert retrieved_admin is not None

    await admin_repository.delete(retrieved_admin)
    await session.commit()

    deleted_admin = await admin_repository.get_by_id(admin_id)
    assert deleted_admin is None
