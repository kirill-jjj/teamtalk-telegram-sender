"""Tests for the handler decorators."""

from unittest.mock import AsyncMock, MagicMock

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, User
import pytest

from bot.telegram_bot.handlers.decorators import ensure_message_context


@pytest.fixture
def mock_callback_query() -> MagicMock:
    """Fixture to create a mock CallbackQuery object."""
    query = MagicMock(spec=CallbackQuery)
    query.from_user = MagicMock(spec=User)
    query.from_user.id = 12345
    query.data = "test_data"
    query.answer = AsyncMock()
    return query


@pytest.fixture
def mock_translator() -> MagicMock:
    """Fixture to create a mock translator."""
    translator = MagicMock()
    translator.gettext.side_effect = lambda text: text  # Identity function
    return translator


@pytest.mark.asyncio
async def test_ensure_message_context_with_message(
    mock_callback_query: MagicMock, mock_translator: MagicMock
) -> None:
    """Test that the decorator calls the function when message context exists."""
    # Arrange
    original_handler = AsyncMock()
    decorated_handler = ensure_message_context(original_handler)
    mock_callback_query.message = MagicMock()

    # Act
    await decorated_handler(mock_callback_query, translator=mock_translator)

    # Assert
    original_handler.assert_awaited_once_with(
        mock_callback_query, translator=mock_translator
    )
    mock_callback_query.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_message_context_without_message(
    mock_callback_query: MagicMock, mock_translator: MagicMock
) -> None:
    """Test that the decorator shows an alert when message context is missing."""
    # Arrange
    original_handler = AsyncMock()
    decorated_handler = ensure_message_context(original_handler)
    mock_callback_query.message = None

    # Act
    result = await decorated_handler(mock_callback_query, translator=mock_translator)

    # Assert
    original_handler.assert_not_awaited()
    mock_callback_query.answer.assert_awaited_once_with(
        "Error processing command.", show_alert=True
    )
    assert result is None


@pytest.mark.asyncio
async def test_ensure_message_context_api_error_on_answer(
    mock_callback_query: MagicMock, mock_translator: MagicMock
) -> None:
    """Test that the decorator handles TelegramAPIError when trying to answer."""
    # Arrange
    original_handler = AsyncMock()
    decorated_handler = ensure_message_context(original_handler)
    mock_callback_query.message = None
    mock_callback_query.answer.side_effect = TelegramAPIError(
        method="answerCallbackQuery", message="error"
    )

    # Act
    result = await decorated_handler(mock_callback_query, translator=mock_translator)

    # Assert
    original_handler.assert_not_awaited()
    mock_callback_query.answer.assert_awaited_once_with(
        "Error processing command.", show_alert=True
    )
    assert result is None


@pytest.mark.asyncio
async def test_ensure_message_context_no_translator_kwarg(
    mock_callback_query: MagicMock,
) -> None:
    """Test that the decorator works even if translator is not in kwargs."""
    # Arrange
    original_handler = AsyncMock()
    decorated_handler = ensure_message_context(original_handler)
    mock_callback_query.message = None

    # Act
    await decorated_handler(mock_callback_query)

    # Assert
    mock_callback_query.answer.assert_awaited_once_with(
        "Error processing command.", show_alert=True
    )
