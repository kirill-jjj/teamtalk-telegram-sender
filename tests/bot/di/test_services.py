"""Tests for the service-related Dishka providers."""

from unittest.mock import AsyncMock, MagicMock

from aiogram.types import User
import pytest

from bot.config import GeneralSettings, Settings
from bot.database.uow import IUnitOfWork
from bot.di.services import ServicesProvider
from bot.services.admin_service import AdminService
from bot.services.cache_service import CacheService
from bot.services.moderation_service import ModerationService
from bot.services.notification_service import NotificationRecipientService
from bot.services.report_service import ReportService
from bot.services.schemas import SettingsViewDTO
from bot.services.subscription_service import SubscriptionService
from bot.services.teamtalk_service import TeamTalkService
from bot.services.user_settings_service import UserSettingsService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.types.bots import EventBot


def test_get_notification_recipient_service() -> None:
    """Test the get_notification_recipient_service provider."""
    # Arrange
    cache = MagicMock(spec=CacheService)
    provider = ServicesProvider()

    # Act
    service = provider.get_notification_recipient_service(cache)

    # Assert
    assert isinstance(service, NotificationRecipientService)


def test_get_teamtalk_service() -> None:
    """Test the get_teamtalk_service provider."""
    # Arrange
    tt_connection = MagicMock(spec=TeamTalkConnection)
    settings = MagicMock(spec=Settings)
    translator_factory = MagicMock()
    provider = ServicesProvider()

    # Act
    service = provider.get_teamtalk_service(tt_connection, settings, translator_factory)

    # Assert
    assert isinstance(service, TeamTalkService)


def test_get_report_service() -> None:
    """Test the get_report_service provider."""
    # Arrange
    settings = MagicMock(spec=Settings)
    uow = MagicMock(spec=IUnitOfWork)
    bot = MagicMock(spec=EventBot)
    teamtalk_service = MagicMock(spec=TeamTalkService)
    provider = ServicesProvider()

    # Act
    service = provider.get_report_service(settings, uow, bot, teamtalk_service)

    # Assert
    assert isinstance(service, ReportService)


def test_get_admin_service() -> None:
    """Test the get_admin_service provider."""
    # Arrange
    uow = MagicMock(spec=IUnitOfWork)
    cache = MagicMock(spec=CacheService)
    event_bus = MagicMock()
    settings = MagicMock(spec=Settings)
    provider = ServicesProvider()

    # Act
    service = provider.get_admin_service(uow, cache, event_bus, settings)

    # Assert
    assert isinstance(service, AdminService)


def test_get_moderation_service() -> None:
    """Test the get_moderation_service provider."""
    # Arrange
    uow = MagicMock(spec=IUnitOfWork)
    subscription_service = MagicMock(spec=SubscriptionService)
    cache = MagicMock(spec=CacheService)
    settings = MagicMock(spec=Settings)
    tt_connection = MagicMock(spec=TeamTalkConnection)
    teamtalk_service = MagicMock(spec=TeamTalkService)
    provider = ServicesProvider()

    # Act
    service = provider.get_moderation_service(
        uow,
        subscription_service,
        cache,
        settings,
        tt_connection,
        teamtalk_service,
    )

    # Assert
    assert isinstance(service, ModerationService)


@pytest.mark.asyncio
async def test_get_user_settings_optional_user_none() -> None:
    """Test get_user_settings_optional when user is None."""
    # Arrange
    provider = ServicesProvider()

    # Act
    result = await provider.get_user_settings_optional(
        None, MagicMock(), MagicMock(), MagicMock()
    )

    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_get_user_settings_optional_user_present() -> None:
    """Test get_user_settings_optional when user is present."""
    # Arrange
    user = User(id=123, is_bot=False, first_name="Test")
    user_settings_service = MagicMock(spec=UserSettingsService)
    user_settings_service.get_user_settings_view = AsyncMock()
    settings = MagicMock(spec=Settings)
    settings.general = MagicMock(spec=GeneralSettings)
    settings.general.default_lang = "en"
    uow = MagicMock(spec=IUnitOfWork)
    uow.__aenter__.return_value = uow
    provider = ServicesProvider()

    # Act
    result = await provider.get_user_settings_optional(
        user, user_settings_service, settings, uow
    )

    # Assert
    user_settings_service.get_user_settings_view.assert_awaited_once_with(
        uow, 123, "en"
    )
    assert result == user_settings_service.get_user_settings_view.return_value


def test_get_user_settings_guaranteed_none() -> None:
    """Test get_user_settings_guaranteed when user_settings is None."""
    # Arrange
    provider = ServicesProvider()

    # Act & Assert
    with pytest.raises(ValueError, match=r"User settings cannot be None."):
        provider.get_user_settings_guaranteed(None)


def test_get_user_settings_guaranteed_present() -> None:
    """Test get_user_settings_guaranteed when user_settings is present."""
    # Arrange
    user_settings = MagicMock(spec=SettingsViewDTO)
    provider = ServicesProvider()

    # Act
    result = provider.get_user_settings_guaranteed(user_settings)

    # Assert
    assert result == user_settings


def test_get_translator_no_user_settings() -> None:
    """Test get_translator when user_settings is None."""
    # Arrange
    settings = MagicMock(spec=Settings)
    settings.general = MagicMock(spec=GeneralSettings)
    settings.general.default_lang = "fr"
    translator_factory = MagicMock()
    provider = ServicesProvider()

    # Act
    translator = provider.get_translator(None, settings, translator_factory)

    # Assert
    translator_factory.assert_called_once_with("fr")
    assert translator == translator_factory.return_value


def test_get_translator_with_user_settings() -> None:
    """Test get_translator when user_settings is present."""
    # Arrange
    user_settings = MagicMock(spec=SettingsViewDTO)
    user_settings.language_code = "de"
    settings = MagicMock(spec=Settings)
    translator_factory = MagicMock()
    provider = ServicesProvider()

    # Act
    translator = provider.get_translator(user_settings, settings, translator_factory)

    # Assert
    translator_factory.assert_called_once_with("de")
    assert translator == translator_factory.return_value
