"""Tests for the user command handlers."""

from gettext import NullTranslations
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Chat, Message, User
import pytest

from bot.config import Settings
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.report_service import ReportService
from bot.services.schemas import SettingsViewDTO
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.handlers.user import (
    on_help_command,
    on_start_command,
    on_start_with_payload,
    on_who_command,
)
from bot.telegram_bot.types.bots import EventBot


@pytest.fixture
def mock_message() -> MagicMock:
    """Fixture for a mocked message."""
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.chat = MagicMock(spec=Chat)
    message.reply = AsyncMock()
    return message


@pytest.fixture
def mock_translator_factory() -> MagicMock:
    """Fixture for a mocked translator factory."""
    translator = MagicMock(spec=NullTranslations)
    translator.gettext.side_effect = lambda text: text  # Identity
    return translator


@pytest.fixture
def mock_deeplink_service() -> MagicMock:
    """Fixture for a mocked deeplink service."""
    service = MagicMock(spec=DeeplinkService)
    service.execute_telegram_deeplink = AsyncMock(return_value=("Success", None))
    return service


@pytest.fixture
def mock_settings() -> MagicMock:
    """Fixture for mocked settings."""
    settings = MagicMock(spec=Settings)
    settings.general = MagicMock()
    settings.general.default_lang = "en"
    return settings


@pytest.fixture
def mock_uow() -> MagicMock:
    """Fixture for a mocked Unit of Work."""
    uow = MagicMock(spec=IUnitOfWork)
    uow.__aenter__ = AsyncMock(return_value=None)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    return uow


@pytest.fixture
def mock_cache() -> MagicMock:
    """Fixture for a mocked cache service."""
    cache = MagicMock(spec=CacheService)
    cache.is_admin.return_value = False
    return cache


@pytest.fixture
def mock_bot() -> MagicMock:
    """Fixture for a mocked bot."""
    return MagicMock(spec=EventBot)


@pytest.fixture
def mock_user_settings() -> MagicMock:
    """Fixture for mocked user settings DTO."""
    user_settings = MagicMock(spec=SettingsViewDTO)
    user_settings.language_code = "en"
    return user_settings


@pytest.fixture
def mock_report_service() -> MagicMock:
    """Fixture for a mocked report service."""
    service = MagicMock(spec=ReportService)
    service.get_who_report_data = AsyncMock(return_value="Report Data")
    return service


@pytest.fixture
def mock_user_settings_service() -> MagicMock:
    """Fixture for a mocked user settings service."""
    return MagicMock(spec=UserSettingsService)


@pytest.mark.asyncio
async def test_on_start_with_payload(
    mock_message: MagicMock,
    mock_translator_factory: MagicMock,
    mock_deeplink_service: MagicMock,
    mock_settings: MagicMock,
    mock_uow: MagicMock,
) -> None:
    """Test the on_start_with_payload handler."""
    # Arrange
    token = "test_token"
    mock_message.from_user.id = 12345

    # Act
    await on_start_with_payload(
        mock_message,
        token,
        mock_translator_factory,
        mock_deeplink_service,
        mock_settings,
        mock_uow,
    )

    # Assert
    mock_deeplink_service.execute_telegram_deeplink.assert_awaited_once_with(
        mock_uow,
        token=token,
        translator=mock_translator_factory,
        telegram_id=mock_message.from_user.id,
        default_lang=mock_settings.general.default_lang,
    )
    mock_uow.commit.assert_awaited_once()
    mock_message.reply.assert_awaited_once_with("Success")


@pytest.mark.asyncio
@patch("bot.telegram_bot.handlers.user.update_user_bot_commands")
async def test_on_start_command_non_admin(
    mock_update_user_bot_commands: AsyncMock,
    mock_message: MagicMock,
    mock_translator_factory: MagicMock,
    mock_cache: MagicMock,
    mock_bot: MagicMock,
    mock_user_settings: MagicMock,
) -> None:
    """Test the on_start_command handler for a non-admin user."""
    # Arrange
    mock_message.from_user.id = 12345
    mock_cache.is_admin.return_value = False

    # Act
    await on_start_command(
        mock_message,
        mock_translator_factory,
        mock_cache,
        mock_bot,
        mock_user_settings,
    )

    # Assert
    mock_message.reply.assert_awaited_once_with(
        "Hello! Use /help to see available commands."
    )
    mock_cache.is_admin.assert_called_once_with(mock_message.from_user.id)
    mock_update_user_bot_commands.assert_not_awaited()


@pytest.mark.asyncio
@patch("bot.telegram_bot.handlers.user.update_user_bot_commands")
async def test_on_start_command_admin(
    mock_update_user_bot_commands: AsyncMock,
    mock_message: MagicMock,
    mock_translator_factory: MagicMock,
    mock_cache: MagicMock,
    mock_bot: MagicMock,
    mock_user_settings: MagicMock,
) -> None:
    """Test the on_start_command handler for an admin user."""
    # Arrange
    mock_message.from_user.id = 12345
    mock_cache.is_admin.return_value = True

    # Act
    await on_start_command(
        mock_message,
        mock_translator_factory,
        mock_cache,
        mock_bot,
        mock_user_settings,
    )

    # Assert
    mock_message.reply.assert_awaited_once_with(
        "Hello! Use /help to see available commands."
    )
    mock_cache.is_admin.assert_called_once_with(mock_message.from_user.id)
    mock_update_user_bot_commands.assert_awaited_once_with(
        telegram_id=mock_message.from_user.id,
        new_lang_code=mock_user_settings.language_code,
        cache=mock_cache,
        bot=mock_bot,
        translator=mock_translator_factory,
    )


@pytest.mark.asyncio
@patch("bot.telegram_bot.handlers.user.format_who_report_to_html")
@patch("aiogram.utils.chat_action.ChatActionSender.typing")
async def test_on_who_command_success(
    mock_chat_action_typing: MagicMock,
    mock_format_who_report_to_html: MagicMock,
    mock_message: MagicMock,
    mock_translator_factory: MagicMock,
    mock_bot: MagicMock,
    mock_report_service: MagicMock,
    mock_cache: MagicMock,
    mock_user_settings_service: MagicMock,
    mock_uow: MagicMock,
) -> None:
    """Test the on_who_command handler for a successful report generation."""
    # Arrange
    mock_message.from_user.id = 12345
    mock_message.chat.id = 67890
    mock_report_service.get_who_report_data.return_value = "Report DTO"
    mock_format_who_report_to_html.return_value = "Formatted Report"

    # Act
    await on_who_command(
        mock_message,
        mock_translator_factory,
        mock_bot,
        mock_report_service,
        mock_cache,
        mock_user_settings_service,
        mock_uow,
    )

    # Assert
    mock_message.from_user.id = 12345
    mock_chat_action_typing.assert_called_once_with(
        bot=mock_bot, chat_id=mock_message.chat.id
    )
    mock_chat_action_typing.return_value.__aenter__.assert_awaited_once()
    mock_chat_action_typing.return_value.__aexit__.assert_awaited_once()
    mock_uow.__aenter__.assert_awaited_once()
    mock_report_service.get_who_report_data.assert_awaited_once_with(
        mock_uow,
        telegram_user_id=mock_message.from_user.id,
        translator=mock_translator_factory,
        cache_service=mock_cache,
        user_settings_service=mock_user_settings_service,
    )
    mock_uow.__aexit__.assert_awaited_once()
    mock_format_who_report_to_html.assert_called_once_with(
        "Report DTO", mock_translator_factory
    )
    mock_message.reply.assert_awaited_once_with("Formatted Report")


@pytest.mark.asyncio
async def test_on_who_command_no_from_user(
    mock_message: MagicMock,
    mock_translator_factory: MagicMock,
    mock_bot: MagicMock,
    mock_report_service: MagicMock,
    mock_cache: MagicMock,
    mock_user_settings_service: MagicMock,
    mock_uow: MagicMock,
) -> None:
    """Test the on_who_command handler when message.from_user is None."""
    # Arrange
    mock_message.from_user = None

    # Act
    await on_who_command(
        mock_message,
        mock_translator_factory,
        mock_bot,
        mock_report_service,
        mock_cache,
        mock_user_settings_service,
        mock_uow,
    )

    # Assert
    mock_message.reply.assert_not_awaited()
    mock_report_service.get_who_report_data.assert_not_awaited()
    mock_uow.__aenter__.assert_not_awaited()
    mock_uow.__aexit__.assert_not_awaited()


@pytest.mark.asyncio
@patch("bot.telegram_bot.handlers.user.format_help_text")
async def test_on_help_command_non_admin(
    mock_format_help_text: MagicMock,
    mock_message: MagicMock,
    mock_translator_factory: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test the on_help_command handler for a non-admin user."""
    # Arrange
    mock_message.from_user.id = 12345
    mock_cache.is_admin.return_value = False
    mock_format_help_text.return_value = "Help text for non-admin"

    # Act
    await on_help_command(mock_message, mock_translator_factory, mock_cache)

    # Assert
    mock_cache.is_admin.assert_called_once_with(mock_message.from_user.id)
    mock_format_help_text.assert_called_once_with(
        mock_translator_factory, is_admin=False
    )
    mock_message.reply.assert_awaited_once_with(
        "Help text for non-admin", parse_mode="HTML"
    )


@pytest.mark.asyncio
@patch("bot.telegram_bot.handlers.user.format_help_text")
async def test_on_help_command_admin(
    mock_format_help_text: MagicMock,
    mock_message: MagicMock,
    mock_translator_factory: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test the on_help_command handler for an admin user."""
    # Arrange
    mock_message.from_user.id = 12345
    mock_cache.is_admin.return_value = True
    mock_format_help_text.return_value = "Help text for admin"

    # Act
    await on_help_command(mock_message, mock_translator_factory, mock_cache)

    # Assert
    mock_cache.is_admin.assert_called_once_with(mock_message.from_user.id)
    mock_format_help_text.assert_called_once_with(
        mock_translator_factory, is_admin=True
    )
    mock_message.reply.assert_awaited_once_with(
        "Help text for admin", parse_mode="HTML"
    )


@pytest.mark.asyncio
async def test_on_help_command_no_from_user(
    mock_message: MagicMock,
    mock_translator_factory: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test the on_help_command handler when message.from_user is None."""
    # Arrange
    mock_message.from_user = None

    # Act
    await on_help_command(mock_message, mock_translator_factory, mock_cache)

    # Assert
    mock_message.reply.assert_not_awaited()
    mock_cache.is_admin.assert_not_called()
