from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import NotificationType
from bot.database.models import MutedUser, UserSettings
from bot.database.repositories.user_repository import UserRepository


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
def user_repository(session: AsyncSession) -> UserRepository:
    """Fixture for a UserRepository instance."""
    return UserRepository(session)


@pytest.mark.asyncio
async def test_get_user_by_id(
    user_repository: UserRepository, session: AsyncSession
) -> None:
    """Test retrieving a UserSettings instance by Telegram ID."""
    user_id = 123
    user_settings = UserSettings(telegram_id=user_id, language_code="en")
    muted_user = MutedUser(
        muted_teamtalk_username="test_muted", user_settings_telegram_id=user_id
    )
    user_settings.muted_users_list.append(muted_user)

    session.add(user_settings)
    await session.commit()
    session.expunge_all()

    retrieved_user = await user_repository.get_by_id(user_id)
    assert retrieved_user is not None
    assert retrieved_user.telegram_id == user_id
    assert len(retrieved_user.muted_users_list) == 1
    assert retrieved_user.muted_users_list[0].muted_teamtalk_username == "test_muted"


@pytest.mark.asyncio
async def test_get_user_by_id_not_found(user_repository: UserRepository) -> None:
    """Test retrieving a non-existent UserSettings instance."""
    retrieved_user = await user_repository.get_by_id(999)
    assert retrieved_user is None


@pytest.mark.asyncio
async def test_get_or_create_existing_user(
    user_repository: UserRepository, session: AsyncSession
) -> None:
    """Test getting an existing user with get_or_create."""
    user_id = 456
    existing_user = UserSettings(telegram_id=user_id, language_code="ru")
    session.add(existing_user)
    await session.commit()
    session.expunge_all()

    user = await user_repository.get_or_create(user_id)
    assert user.telegram_id == user_id
    assert user.language_code == "ru"
    assert len(user.muted_users_list) == 0


@pytest.mark.asyncio
async def test_get_or_create_new_user(
    user_repository: UserRepository,
    session: AsyncSession,  # noqa: ARG001
) -> None:
    """Test creating a new user with get_or_create."""
    user_id = 789
    defaults = {"language_code": "uk", "teamtalk_username": "new_tt_user"}
    user = await user_repository.get_or_create(user_id, defaults=defaults)

    assert user.telegram_id == user_id
    assert user.language_code == "uk"
    assert user.teamtalk_username == "new_tt_user"
    assert len(user.muted_users_list) == 0

    retrieved_user = await user_repository.get_by_id(user_id)
    assert retrieved_user is not None
    assert retrieved_user.telegram_id == user_id


@pytest.mark.asyncio
async def test_save_user_settings(
    user_repository: UserRepository, session: AsyncSession
) -> None:
    """Test saving (updating) user settings."""
    user_id = 111
    user_settings = UserSettings(telegram_id=user_id, language_code="en")
    session.add(user_settings)
    await session.commit()
    session.expunge_all()

    retrieved_user = await user_repository.get_by_id(user_id)
    assert retrieved_user is not None
    retrieved_user.language_code = "fr"
    retrieved_user.teamtalk_username = "updated_tt"

    await user_repository.save(retrieved_user)
    await session.commit()
    session.expunge_all()

    updated_user = await user_repository.get_by_id(user_id)
    assert updated_user.language_code == "fr"
    assert updated_user.teamtalk_username == "updated_tt"


@pytest.mark.asyncio
async def test_get_all_users(
    user_repository: UserRepository, session: AsyncSession
) -> None:
    """Test retrieving all UserSettings instances."""
    user1 = UserSettings(telegram_id=1, language_code="en")
    user2 = UserSettings(telegram_id=2, language_code="ru")
    session.add(user1)
    session.add(user2)
    await session.commit()
    session.expunge_all()

    all_users = await user_repository.get_all()
    assert len(all_users) == 2
    assert {u.telegram_id for u in all_users} == {1, 2}


@pytest.mark.asyncio
async def test_get_by_ids(
    user_repository: UserRepository, session: AsyncSession
) -> None:
    """Test retrieving multiple UserSettings instances by IDs."""
    user1 = UserSettings(telegram_id=10, language_code="en")
    user2 = UserSettings(telegram_id=20, language_code="ru")
    user3 = UserSettings(telegram_id=30, language_code="uk")
    session.add(user1)
    session.add(user2)
    session.add(user3)
    await session.commit()
    session.expunge_all()

    retrieved_users = await user_repository.get_by_ids([10, 30])
    assert len(retrieved_users) == 2
    assert {u.telegram_id for u in retrieved_users} == {10, 30}


@pytest.mark.asyncio
async def test_get_notification_recipients(
    user_repository: UserRepository,
) -> None:
    """Test retrieving notification recipients."""
    mock_result = MagicMock()
    mock_result.all.return_value = [(1, "en"), (2, "ru")]
    user_repository._session.execute = AsyncMock(return_value=mock_result)

    recipients = await user_repository.get_notification_recipients(
        [1, 2, 3], "test_user", NotificationType.JOIN
    )

    assert recipients == [(1, "en"), (2, "ru")]
    user_repository._session.execute.assert_called_once()
