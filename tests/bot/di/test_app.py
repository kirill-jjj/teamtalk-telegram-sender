"""Tests for the application-level Dishka providers."""

from collections.abc import Callable
from gettext import NullTranslations
from unittest.mock import MagicMock, patch

from cachetools import LRUCache

from bot.config import OperationalParameters, Settings
from bot.core.languages import DOMAIN, LOCALE_DIR, LanguageInfo
from bot.di.app import AppProvider, create_translator_factory
from bot.event_bus.bus import EventBus
from bot.services.cache_service import CacheService


@patch("bot.di.app.gettext.NullTranslations")
@patch("bot.di.app.gettext.translation")
def test_create_translator_factory_none_lang_code(
    mock_gettext_translation: MagicMock,
    mock_null_translations: MagicMock,
) -> None:
    """Test create_translator_factory with None lang_code."""
    # Arrange
    translator_cache = {}
    factory = create_translator_factory(translator_cache)

    # Act
    translator = factory(None)

    # Assert
    mock_null_translations.assert_called_once()
    assert translator == mock_null_translations.return_value
    mock_gettext_translation.assert_not_called()


@patch("bot.di.app.gettext.NullTranslations")
@patch("bot.di.app.gettext.translation")
def test_create_translator_factory_cached_lang_code(
    mock_gettext_translation: MagicMock,
    mock_null_translations: MagicMock,
) -> None:
    """Test create_translator_factory with cached lang_code."""
    # Arrange
    cached_translator = MagicMock(spec=NullTranslations)
    translator_cache = {"en": cached_translator}
    factory = create_translator_factory(translator_cache)

    # Act
    translator = factory("en")

    # Assert
    assert translator == cached_translator
    mock_null_translations.assert_not_called()
    mock_gettext_translation.assert_not_called()


@patch("bot.di.app.gettext.NullTranslations")
@patch("bot.di.app.gettext.translation")
def test_create_translator_factory_new_lang_code_success(
    mock_gettext_translation: MagicMock,
    mock_null_translations: MagicMock,
) -> None:
    """Test create_translator_factory with new lang_code and successful translation."""
    # Arrange
    translator_cache = {}
    factory = create_translator_factory(translator_cache)
    mock_gettext_translation.return_value = MagicMock(spec=NullTranslations)

    # Act
    translator = factory("fr")

    # Assert
    mock_gettext_translation.assert_called_once_with(
        DOMAIN, localedir=str(LOCALE_DIR), languages=["fr"]
    )
    assert translator == mock_gettext_translation.return_value
    assert translator_cache["fr"] == translator
    mock_null_translations.assert_not_called()


@patch("bot.di.app.gettext.NullTranslations")
@patch("bot.di.app.gettext.translation", side_effect=FileNotFoundError)
def test_create_translator_factory_new_lang_code_file_not_found(
    mock_gettext_translation: MagicMock,
    mock_null_translations: MagicMock,
) -> None:
    """Test create_translator_factory with new lang_code and FileNotFoundError."""
    # Arrange
    translator_cache = {}
    factory = create_translator_factory(translator_cache)

    # Act
    translator = factory("de")

    # Assert
    mock_gettext_translation.assert_called_once_with(
        DOMAIN, localedir=str(LOCALE_DIR), languages=["de"]
    )
    mock_null_translations.assert_called_once()
    assert translator == mock_null_translations.return_value
    assert translator_cache["de"] == translator


# AppProvider Tests


def test_app_provider_init() -> None:
    """Test the AppProvider initialization."""
    # Arrange
    settings = MagicMock(spec=Settings)
    config_path = "/path/to/config.toml"

    # Act
    provider = AppProvider(settings, config_path)

    # Assert
    assert provider._settings == settings
    assert provider._config_path == config_path


def test_get_config_path() -> None:
    """Test the get_config_path provider method."""
    # Arrange
    settings = MagicMock(spec=Settings)
    config_path = "/path/to/config.toml"
    provider = AppProvider(settings, config_path)

    # Act
    result = provider.get_config_path()

    # Assert
    assert result == config_path


def test_get_settings() -> None:
    """Test the get_settings provider method."""
    # Arrange
    settings = MagicMock(spec=Settings)
    config_path = "/path/to/config.toml"
    provider = AppProvider(settings, config_path)

    # Act
    result = provider.get_settings()

    # Assert
    assert result == settings


def test_get_translator_cache() -> None:
    """Test the get_translator_cache provider method."""
    # Arrange
    settings = MagicMock(spec=Settings)
    provider = AppProvider(settings, "config.toml")

    # Act
    cache = provider.get_translator_cache()

    # Assert
    assert cache == {}


@patch("bot.di.app.discover_languages")
def test_get_available_languages(mock_discover_languages: MagicMock) -> None:
    """Test the get_available_languages provider method."""
    # Arrange
    settings = MagicMock(spec=Settings)
    provider = AppProvider(settings, "config.toml")
    mock_discover_languages.return_value = [MagicMock(spec=LanguageInfo)]

    # Act
    languages = provider.get_available_languages()

    # Assert
    mock_discover_languages.assert_called_once()
    assert languages == mock_discover_languages.return_value


def test_get_translator_factory() -> None:
    """Test the get_translator_factory provider method."""
    # Arrange
    settings = MagicMock(spec=Settings)
    provider = AppProvider(settings, "config.toml")
    translator_cache = {}

    # Act
    factory = provider.get_translator_factory(translator_cache)

    # Assert
    assert isinstance(factory, Callable)


def test_get_str_translator_factory() -> None:
    """Test the get_str_translator_factory provider method."""
    # Arrange
    settings = MagicMock(spec=Settings)
    provider = AppProvider(settings, "config.toml")
    mock_translator_factory = MagicMock(spec=Callable[[str | None], NullTranslations])

    # Act
    str_factory = provider.get_str_translator_factory(mock_translator_factory)
    result = str_factory("en")

    # Assert
    assert isinstance(str_factory, Callable)
    mock_translator_factory.assert_called_once_with("en")
    assert result == mock_translator_factory.return_value


def test_get_event_bus() -> None:
    """Test the get_event_bus provider method."""
    # Arrange
    settings = MagicMock(spec=Settings)
    provider = AppProvider(settings, "config.toml")

    # Act
    event_bus = provider.get_event_bus()

    # Assert
    assert isinstance(event_bus, EventBus)


def test_get_cache_service() -> None:
    """Test the get_cache_service provider method."""
    # Arrange
    settings = MagicMock(spec=Settings)
    settings.operational_parameters = MagicMock(spec=OperationalParameters)
    settings.operational_parameters.user_settings_cache_max_size = 100
    provider = AppProvider(settings, "config.toml")

    # Act
    cache_service = provider.get_cache_service(settings)

    # Assert
    assert isinstance(cache_service, CacheService)
    assert isinstance(cache_service._user_settings_cache, LRUCache)
    assert cache_service._user_settings_cache.maxsize == 100
    assert isinstance(cache_service._admin_ids_cache, set)
    assert isinstance(cache_service._subscribed_users_cache, set)
