"""Tests for the IsAdmin filter."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery, Chat, Message, User
import pytest

from bot.services.cache_service import CacheService
from bot.telegram_bot.filters.admin import IsAdmin


@pytest.fixture
def mock_cache_service() -> MagicMock:
    """Fixture for a mocked CacheService."""
    return MagicMock(spec=CacheService)


@pytest.fixture
def mock_dishka_container(mock_cache_service: MagicMock) -> AsyncMock:
    """Fixture for a mocked dishka container that provides the mock CacheService."""
    container = AsyncMock()
    container.get.return_value = mock_cache_service
    return container


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "is_admin_return", "expected_result"),
    [
        (Message, True, True),
        (Message, False, False),
        (CallbackQuery, True, True),
        (CallbackQuery, False, False),
    ],
)
async def test_is_admin_filter(
    event_type: type[Message | CallbackQuery],
    is_admin_return: bool,
    expected_result: bool,
    mock_cache_service: MagicMock,
    mock_dishka_container: AsyncMock,
) -> None:
    """Test the IsAdmin filter with different event types and cache responses."""
    # Arrange
    user_id = 123
    mock_cache_service.is_admin.return_value = is_admin_return

    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=456, type="private")

    if event_type is Message:
        event = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=chat,
            from_user=user,
            text="test",
        )
    else:
        event = CallbackQuery(
            id="1", from_user=user, chat_instance="instance", data="data"
        )

    filter_instance = IsAdmin()
    data = {"dishka_container": mock_dishka_container}

    # Act
    result = await filter_instance(event, **data)

    # Assert
    assert result is expected_result
    mock_cache_service.is_admin.assert_called_once_with(user_id)
    mock_dishka_container.get.assert_called_once_with(CacheService)


@pytest.mark.asyncio
async def test_is_admin_filter_no_user(
    mock_dishka_container: AsyncMock,
) -> None:
    """Test the IsAdmin filter when the event has no from_user."""
    # Arrange
    chat = Chat(id=456, type="private")
    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        from_user=None,
        text="test",
    )
    filter_instance = IsAdmin()
    data = {"dishka_container": mock_dishka_container}

    # Act
    result = await filter_instance(event, **data)

    # Assert
    assert result is False


@pytest.mark.asyncio
async def test_is_admin_filter_no_container() -> None:
    """Test the IsAdmin filter when the dishka_container is not in the data."""
    # Arrange
    user = User(id=123, is_bot=False, first_name="Test")
    chat = Chat(id=456, type="private")
    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        from_user=user,
        text="test",
    )
    filter_instance = IsAdmin()
    data = {}  # No container

    # Act & Assert
    with pytest.raises(KeyError):
        await filter_instance(event, **data)


@pytest.mark.asyncio
async def test_is_admin_filter_none_container() -> None:
    """Test the IsAdmin filter when the dishka_container is None."""
    # Arrange
    user = User(id=123, is_bot=False, first_name="Test")
    chat = Chat(id=456, type="private")
    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        from_user=user,
        text="test",
    )
    filter_instance = IsAdmin()
    data = {"dishka_container": None}

    # Act
    result = await filter_instance(event, **data)

    # Assert
    assert result is False
