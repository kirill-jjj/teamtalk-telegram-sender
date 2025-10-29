"""Tests for the language utilities."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bot.core.languages import discover_languages


@pytest.fixture
def mock_locales_dir(tmp_path: Path) -> Path:
    """Fixture for a mocked locales directory."""
    return tmp_path / "locales"


def test_discover_languages_no_locales_dir(mock_locales_dir: Path) -> None:
    """Test discover_languages when the locales directory does not exist."""
    # Arrange
    # (no arrangement needed, the directory is not created)

    # Act
    languages = discover_languages(mock_locales_dir)

    # Assert
    assert len(languages) == 1
    assert languages[0]["code"] == "en"
    assert languages[0]["native_name"] == "English"

    assert languages[0]["native_name"] == "English"


@patch("gettext.translation")
def test_discover_languages_with_translation(
    mock_gettext_translation: MagicMock, mock_locales_dir: Path
) -> None:
    """Test discover_languages with a simple translation."""

    # Arrange

    ru_dir = mock_locales_dir / "ru" / "LC_MESSAGES"

    ru_dir.mkdir(parents=True)

    (ru_dir / "messages.mo").touch()

    mock_translator = MagicMock()

    mock_translator.gettext.return_value = "Русский"

    mock_gettext_translation.return_value = mock_translator

    # Act

    languages = discover_languages(mock_locales_dir)

    # Assert

    assert len(languages) == 2

    assert {"code": "en", "native_name": "English"} in languages

    assert {"code": "ru", "native_name": "Русский"} in languages


@patch("gettext.translation")
def test_discover_languages_untranslated_native_name(
    mock_gettext_translation: MagicMock, mock_locales_dir: Path
) -> None:
    """Test discover_languages when the native name is not translated."""
    # Arrange
    de_dir = mock_locales_dir / "de" / "LC_MESSAGES"
    de_dir.mkdir(parents=True)
    (de_dir / "messages.mo").touch()

    mock_translator = MagicMock()
    mock_translator.gettext.return_value = "language_native_name"
    mock_gettext_translation.return_value = mock_translator

    # Act
    languages = discover_languages(mock_locales_dir)

    # Assert
    assert len(languages) == 2
    assert {"code": "en", "native_name": "English"} in languages
    assert {"code": "de", "native_name": "de"} in languages


@patch("gettext.translation", side_effect=OSError("File not found"))
def test_discover_languages_os_error(
    __mock_gettext_translation: MagicMock,
    mock_locales_dir: Path,
) -> None:
    """Test discover_languages when gettext.translation raises an OSError."""
    # Arrange
    fr_dir = mock_locales_dir / "fr" / "LC_MESSAGES"
    fr_dir.mkdir(parents=True)
    (fr_dir / "messages.mo").touch()

    # Act
    languages = discover_languages(mock_locales_dir)

    # Assert
    assert len(languages) == 2
    assert {"code": "en", "native_name": "English"} in languages
    assert {"code": "fr", "native_name": "fr"} in languages
