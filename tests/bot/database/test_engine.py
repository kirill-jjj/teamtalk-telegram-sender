"""Tests for the database engine and session factory setup."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.engine import Engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.config import DatabaseSettings, Settings
from bot.database.engine import create_session_factory


@pytest.fixture
def mock_settings() -> MagicMock:
    """Fixture for mocked settings."""
    settings = MagicMock(spec=Settings)
    settings.database = MagicMock(spec=DatabaseSettings)
    settings.database.db_file = "test.db"
    settings._config_dir = Path("/app/config")
    return settings


@patch("bot.database.engine.create_async_engine")
@patch("bot.database.engine.sessionmaker")
def test_create_session_factory_relative_path(
    mock_sessionmaker: MagicMock,
    mock_create_async_engine: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Test create_session_factory with a relative database file path."""
    # Arrange
    expected_db_path = mock_settings._config_dir / mock_settings.database.db_file
    mock_settings.database.db_file = "test.db"

    # Act
    session_factory = create_session_factory(mock_settings)

    # Assert
    mock_create_async_engine.assert_called_once_with(
        f"sqlite+aiosqlite:///{expected_db_path.resolve()}"
    )
    mock_sessionmaker.assert_called_once_with(
        bind=mock_create_async_engine.return_value,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    assert session_factory == mock_sessionmaker.return_value


@patch("bot.database.engine.create_async_engine")
@patch("bot.database.engine.sessionmaker")
def test_create_session_factory_absolute_path(
    mock_sessionmaker: MagicMock,
    mock_create_async_engine: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Test create_session_factory with an absolute database file path."""
    # Arrange
    absolute_db_path = Path("/var/data/prod.db")
    mock_settings.database.db_file = str(absolute_db_path)

    # Act
    session_factory = create_session_factory(mock_settings)

    # Assert
    mock_create_async_engine.assert_called_once_with(
        f"sqlite+aiosqlite:///{absolute_db_path.resolve()}"
    )
    mock_sessionmaker.assert_called_once_with(
        bind=mock_create_async_engine.return_value,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    assert session_factory == mock_sessionmaker.return_value


@patch("bot.database.engine.create_async_engine")
@patch("bot.database.engine.sessionmaker")
@patch("bot.database.engine.event")
def test_set_sqlite_pragma_event_listener(
    mock_event: MagicMock,
    _mock_sessionmaker: MagicMock,  # noqa: PT019
    _mock_create_async_engine: MagicMock,  # noqa: PT019
    mock_settings: MagicMock,
) -> None:
    """Test the set_sqlite_pragma event listener is registered and called correctly."""

    # Arrange

    decorator_mock = MagicMock()

    mock_event.listens_for.return_value = decorator_mock

    # Act

    create_session_factory(mock_settings)

    # Assert that the event listener was registered

    mock_event.listens_for.assert_called_once_with(Engine, "connect")

    # The decorator is called with the function

    set_sqlite_pragma_func = decorator_mock.call_args[0][0]

    mock_dbapi_connection = MagicMock()

    mock_cursor = MagicMock()

    mock_dbapi_connection.cursor.return_value = mock_cursor

    set_sqlite_pragma_func(mock_dbapi_connection, MagicMock())

    mock_dbapi_connection.cursor.assert_called_once()

    mock_cursor.execute.assert_any_call("PRAGMA journal_mode=WAL;")

    mock_cursor.execute.assert_any_call("PRAGMA synchronous=NORMAL;")

    mock_cursor.close.assert_called_once()
