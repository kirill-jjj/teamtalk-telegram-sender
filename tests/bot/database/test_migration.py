"""Tests for the database migration utilities."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config import DatabaseSettings, Settings
from bot.database.migration import run_migrations


@pytest.fixture
def mock_settings(tmp_path: Path) -> MagicMock:
    """Fixture for mocked settings."""
    settings = MagicMock(spec=Settings)
    settings.database = MagicMock(spec=DatabaseSettings)
    settings.database.db_file = "test.db"
    settings._config_dir = tmp_path
    return settings


@pytest.fixture
def mock_project_root(tmp_path: Path) -> Path:
    """Fixture for a mocked project root."""
    alembic_ini = tmp_path / "alembic.ini"
    alembic_ini.touch()
    return tmp_path


@pytest.mark.asyncio
@patch("bot.database.migration.Config")
@patch("bot.database.migration.command")
@patch("asyncio.to_thread")
async def test_run_migrations(
    mock_to_thread: AsyncMock,
    mock_command: MagicMock,
    mock_config: MagicMock,
    mock_settings: MagicMock,
    mock_project_root: Path,
) -> None:
    """Test the run_migrations function."""
    # Arrange
    mock_command.upgrade = MagicMock()

    # Act
    await run_migrations(mock_settings, mock_project_root)

    # Assert
    mock_config.assert_called_once_with(str(mock_project_root / "alembic.ini"))
    mock_config.return_value.set_main_option.assert_called_once()
    mock_to_thread.assert_awaited_once_with(
        mock_command.upgrade, mock_config.return_value, "head"
    )


@pytest.mark.asyncio
@patch("bot.database.migration.Config")
@patch("bot.database.migration.command")
@patch("asyncio.to_thread")
async def test_run_migrations_exception(
    mock_to_thread: AsyncMock,
    _mock_command: MagicMock,  # noqa: PT019
    _mock_config: MagicMock,  # noqa: PT019
    mock_settings: MagicMock,
    mock_project_root: Path,
) -> None:
    """Test the run_migrations function when command.upgrade raises an exception."""
    # Arrange
    mock_to_thread.side_effect = Exception("Test Exception")

    # Act & Assert
    with pytest.raises(Exception, match="Test Exception"):
        await run_migrations(mock_settings, mock_project_root)
