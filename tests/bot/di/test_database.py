"""Tests for the database-related Dishka providers."""

from unittest.mock import MagicMock, patch

from bot.config import Settings
from bot.database.uow import SqlModelUnitOfWork
from bot.di.database import DatabaseProvider


@patch("bot.di.database.create_session_factory")
def test_get_session_factory(mock_create_session_factory: MagicMock) -> None:
    """Test the get_session_factory provider."""
    # Arrange
    settings = MagicMock(spec=Settings)
    provider = DatabaseProvider()

    # Act
    session_factory = provider.get_session_factory(settings)

    # Assert
    mock_create_session_factory.assert_called_once_with(settings)
    assert session_factory == mock_create_session_factory.return_value


def test_get_uow() -> None:
    """Test the get_uow provider."""
    # Arrange
    session_factory = MagicMock()
    provider = DatabaseProvider()

    # Act
    uow = provider.get_uow(session_factory)

    # Assert
    assert isinstance(uow, SqlModelUnitOfWork)
    assert uow._session_factory == session_factory
