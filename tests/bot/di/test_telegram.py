"""Tests for the Telegram-related Dishka providers."""

from unittest.mock import MagicMock, patch

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject, User
from dishka import AsyncContainer

from bot.config import Settings, TelegramSettings
from bot.di.telegram import TelegramProvider, _create_bot
from bot.event_bus.bus import EventBus
from bot.services.cache_service import CacheService
from bot.services.notification_service import NotificationRecipientService
from bot.telegram_bot.handlers.event_subscribers import TelegramNotificationHandler
from bot.telegram_bot.types.bots import EventBot, MessageBot


def test_create_bot() -> None:
    """Test the _create_bot helper function."""
    # Arrange
    token = "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-1234567890"

    # Act
    bot = _create_bot(token)

    # Assert
    assert isinstance(bot, Bot)
    assert bot.token == token
    assert isinstance(bot.default, DefaultBotProperties)
    assert bot.default.parse_mode == ParseMode.HTML


@patch("bot.di.telegram._create_bot")
def test_get_bot_event(mock_create_bot: MagicMock) -> None:
    """Test the get_bot_event provider."""
    # Arrange
    settings = MagicMock(spec=Settings)
    settings.telegram = MagicMock(spec=TelegramSettings)
    settings.telegram.event_token = "event_token"
    provider = TelegramProvider()

    # Act
    bot = provider.get_bot_event(settings)

    # Assert
    mock_create_bot.assert_called_once_with(token="event_token")
    assert bot == mock_create_bot.return_value


@patch("bot.di.telegram._create_bot")
def test_get_bot_message(mock_create_bot: MagicMock) -> None:
    """Test the get_bot_message provider."""
    # Arrange
    settings = MagicMock(spec=Settings)
    settings.telegram = MagicMock(spec=TelegramSettings)
    settings.telegram.message_token = "message_token"
    provider = TelegramProvider()

    # Act
    bot = provider.get_bot_message(settings)

    # Assert
    mock_create_bot.assert_called_once_with(token="message_token")
    assert bot == mock_create_bot.return_value


def test_get_dispatcher() -> None:
    """Test the get_dispatcher provider."""
    # Arrange
    provider = TelegramProvider()

    # Act
    dispatcher = provider.get_dispatcher()

    # Assert
    assert isinstance(dispatcher, Dispatcher)


def test_get_telegram_notification_handler() -> None:
    """Test the get_telegram_notification_handler provider."""
    # Arrange
    event_bot = MagicMock(spec=EventBot)
    message_bot = MagicMock(spec=MessageBot)
    cache = MagicMock(spec=CacheService)
    settings = MagicMock(spec=Settings)
    translator_factory = MagicMock()
    event_bus = MagicMock(spec=EventBus)
    recipient_service = MagicMock(spec=NotificationRecipientService)
    app_container = MagicMock(spec=AsyncContainer)
    provider = TelegramProvider()

    # Act
    handler = provider.get_telegram_notification_handler(
        event_bot,
        message_bot,
        cache,
        settings,
        translator_factory,
        event_bus,
        recipient_service,
        app_container,
    )

    # Assert
    assert isinstance(handler, TelegramNotificationHandler)


def test_get_user_from_event_with_user() -> None:
    """Test get_user_from_event when the event has a user."""
    # Arrange
    user = User(id=123, is_bot=False, first_name="Test")
    event = MagicMock(spec=TelegramObject)
    event.from_user = user
    provider = TelegramProvider()

    # Act
    extracted_user = provider.get_user_from_event(event)

    # Assert
    assert extracted_user == user


def test_get_user_from_event_no_user() -> None:
    """Test get_user_from_event when the event has no user."""
    # Arrange
    event = MagicMock(spec=TelegramObject)
    event.from_user = None
    provider = TelegramProvider()

    # Act
    extracted_user = provider.get_user_from_event(event)

    # Assert
    assert extracted_user is None
