"""Tests for the unknown command handler."""

from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Chat, Message, User
import pytest

from bot.telegram_bot.handlers.unknown import on_unknown_message


@pytest.fixture
def mock_message() -> MagicMock:
    """Fixture to create a mock Message object."""
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 12345
    message.chat = MagicMock(spec=Chat)
    message.chat.id = 54321
    message.reply = AsyncMock()
    return message


@pytest.fixture
def mock_translator() -> MagicMock:
    """Fixture to create a mock translator."""
    translator = MagicMock()
    translator.gettext = lambda text: text  # Simple identity function for _()
    return translator


@pytest.mark.asyncio
async def test_on_unknown_command(
    mock_message: MagicMock, mock_translator: MagicMock
) -> None:
    """Test that an unknown command receives a reply."""
    # Arrange
    mock_message.text = "/some_unknown_command"

    # Act
    await on_unknown_message(mock_message, mock_translator)

    # Assert
    mock_message.reply.assert_awaited_once_with(
        "Unknown command. Use /help to see available commands."
    )


@pytest.mark.asyncio
async def test_on_random_text_message(
    mock_message: MagicMock, mock_translator: MagicMock
) -> None:
    """Test that a random text message is ignored."""
    # Arrange
    mock_message.text = "just some random text"

    # Act
    await on_unknown_message(mock_message, mock_translator)

    # Assert
    mock_message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_without_text(
    mock_message: MagicMock, mock_translator: MagicMock
) -> None:
    """Test that a message without text (e.g., a sticker) is ignored."""
    # Arrange
    mock_message.text = None

    # Act
    await on_unknown_message(mock_message, mock_translator)

    # Assert
    mock_message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_without_user(
    mock_message: MagicMock, mock_translator: MagicMock
) -> None:
    """Test that a message without a user (e.g., a channel post) is ignored."""
    # Arrange
    mock_message.text = "/some_command"
    mock_message.from_user = None

    # Act
    await on_unknown_message(mock_message, mock_translator)

    # Assert
    mock_message.reply.assert_not_awaited()
