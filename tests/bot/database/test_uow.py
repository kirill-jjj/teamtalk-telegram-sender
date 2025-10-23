"""Tests for the Unit of Work (UoW) pattern implementation."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.exceptions import SessionNotAvailableError
from bot.database.engine import AsyncSessionFactoryType
from bot.database.repositories.admin_repository import AdminRepository
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.database.uow import SqlModelUnitOfWork


@pytest.fixture
def mock_session() -> AsyncMock:
    """Fixture for a mock AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_session_factory(mock_session: AsyncMock) -> AsyncSessionFactoryType:
    """Fixture for a mock AsyncSessionFactoryType."""
    return MagicMock(return_value=mock_session)


@pytest.fixture
def uow(mock_session_factory: AsyncSessionFactoryType) -> SqlModelUnitOfWork:
    """Fixture for a SqlModelUnitOfWork instance."""
    return SqlModelUnitOfWork(session_factory=mock_session_factory)


@pytest.mark.asyncio
async def test_uow_aenter_initializes_repositories(
    uow: SqlModelUnitOfWork, mock_session: AsyncMock
) -> None:
    """Test that __aenter__ correctly initializes all repositories."""
    async with uow:
        assert isinstance(uow.users, UserRepository)
        assert isinstance(uow.bans, BanRepository)
        assert isinstance(uow.admins, AdminRepository)
        assert isinstance(uow.subscribers, SubscriberRepository)
        assert isinstance(uow.deeplinks, DeeplinkRepository)

        assert uow.users._session is mock_session
        assert uow.bans._session is mock_session
        assert uow.admins._session is mock_session
        assert uow.subscribers._session is mock_session
        assert uow.deeplinks._session is mock_session


@pytest.mark.asyncio
async def test_uow_aexit_commits_on_success(
    uow: SqlModelUnitOfWork, mock_session: AsyncMock
) -> None:
    """Test that __aexit__ commits the session if no exception occurs."""
    async with uow:
        pass  # No exception raised

    mock_session.commit.assert_called_once()
    mock_session.rollback.assert_not_called()
    mock_session.close.assert_called_once()
    assert uow._session is None


@pytest.mark.asyncio
async def test_uow_aexit_rolls_back_on_exception(
    uow: SqlModelUnitOfWork, mock_session: AsyncMock
) -> None:
    """Test that __aexit__ rolls back the session if an exception occurs."""
    test_exception_message = "Test exception"
    with pytest.raises(ValueError, match=test_exception_message):
        async with uow:
            raise ValueError(test_exception_message)

    mock_session.commit.assert_not_called()
    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
    assert uow._session is None


@pytest.mark.asyncio
async def test_uow_commit_method(
    uow: SqlModelUnitOfWork, mock_session: AsyncMock
) -> None:
    """Test the commit method directly."""
    uow._session = mock_session  # Manually set the session for isolated testing
    await uow.commit()

    mock_session.commit.assert_called_once()
    # Ensure session is closed after the test, as __aexit__ won't do it here
    await uow._session.close()
    uow._session = None


@pytest.mark.asyncio
async def test_uow_rollback_method(
    uow: SqlModelUnitOfWork, mock_session: AsyncMock
) -> None:
    """Test the rollback method directly, including SQLAlchemyError propagation."""
    uow._session = mock_session  # Manually set the session for isolated testing
    mock_session.rollback.side_effect = SQLAlchemyError("Rollback failed")

    with pytest.raises(SQLAlchemyError):
        await uow.rollback()

    mock_session.rollback.assert_called_once()
    # Ensure session is closed after the test, as __aexit__ won't do it here
    await uow._session.close()
    uow._session = None


@pytest.mark.asyncio
async def test_uow_session_property_access(
    uow: SqlModelUnitOfWork, mock_session: AsyncMock
) -> None:
    """Test accessing the session property within the context manager."""
    async with uow:
        session = uow.session
        assert session is mock_session


def test_uow_session_property_not_available_outside_context(
    uow: SqlModelUnitOfWork,
) -> None:
    """Test that accessing session outside context raises SessionNotAvailableError."""
    with pytest.raises(SessionNotAvailableError):
        _ = uow.session


@pytest.mark.asyncio
async def test_uow_aexit_handles_sqlalchemy_error(
    uow: SqlModelUnitOfWork, mock_session: AsyncMock
) -> None:
    """Test that __aexit__ handles SQLAlchemyError during commit/rollback."""
    mock_session.commit.side_effect = SQLAlchemyError("Commit failed")

    with pytest.raises(SQLAlchemyError):
        async with uow:
            pass

    mock_session.commit.assert_called_once()
    mock_session.close.assert_called_once()
    assert uow._session is None


@pytest.mark.asyncio
async def test_uow_aexit_handles_sqlalchemy_error_during_rollback(
    uow: SqlModelUnitOfWork, mock_session: AsyncMock
) -> None:
    """Test that __aexit__ handles SQLAlchemyError during rollback."""
    rollback_failed_message = "Rollback failed"
    test_exception_message = "Test exception to trigger rollback"
    mock_session.rollback.side_effect = SQLAlchemyError(rollback_failed_message)

    with pytest.raises(SQLAlchemyError, match=rollback_failed_message):
        async with uow:
            raise ValueError(test_exception_message)

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
    assert uow._session is None
