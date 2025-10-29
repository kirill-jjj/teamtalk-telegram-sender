"""Tests for the subscription filters."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Chat, Message, User
import pytest

from bot.services.cache_service import CacheService
from bot.telegram_bot.filters.subscription import IsSubscribed


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
    ("is_subscribed_return", "expected_result"),
    [(True, True), (False, False)],
)
async def test_is_subscribed_filter(
    is_subscribed_return: bool,
    expected_result: bool,
    mock_cache_service: MagicMock,
    mock_dishka_container: AsyncMock,
) -> None:
    """Test the IsSubscribed filter for a regular message."""
    # Arrange
    user_id = 123
    mock_cache_service.is_subscribed.return_value = is_subscribed_return

    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=456, type="private")
    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        from_user=user,
        text="/who",
    )

    filter_instance = IsSubscribed()
    data = {"dishka_container": mock_dishka_container}

    # Act
    result = await filter_instance(event, **data)

    # Assert
    assert result is expected_result
    mock_cache_service.is_subscribed.assert_called_once_with(user_id)


@pytest.mark.asyncio
async def test_is_subscribed_filter_with_deeplink(
    mock_cache_service: MagicMock,
    mock_dishka_container: AsyncMock,
) -> None:
    """Test that the IsSubscribed filter always passes for /start with a deeplink."""
    # Arrange
    user = User(id=123, is_bot=False, first_name="Test")
    chat = Chat(id=456, type="private")
    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        from_user=user,
        text="/start some_payload",
    )

    filter_instance = IsSubscribed()
    data = {"dishka_container": mock_dishka_container}

    # Act
    result = await filter_instance(event, **data)

    # Assert
    assert result is True
    mock_cache_service.is_subscribed.assert_not_called()


@pytest.mark.asyncio
async def test_is_subscribed_filter_no_user(
    mock_dishka_container: AsyncMock,
) -> None:
    """Test the IsSubscribed filter when the event has no from_user."""
    # Arrange
    chat = Chat(id=456, type="private")
    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        from_user=None,
        text="/who",
    )
    filter_instance = IsSubscribed()
    data = {"dishka_container": mock_dishka_container}

    # Act
    result = await filter_instance(event, **data)

    # Assert
    assert result is False


@pytest.mark.asyncio
async def test_is_subscribed_filter_no_container() -> None:
    """Test the IsSubscribed filter when the dishka_container is not in the data."""
    # Arrange
    user = User(id=123, is_bot=False, first_name="Test")
    chat = Chat(id=456, type="private")
    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        from_user=user,
        text="/who",
    )
    filter_instance = IsSubscribed()
    data = {}  # No container

    # Act & Assert
    with pytest.raises(KeyError):
        await filter_instance(event, **data)


@pytest.mark.asyncio
async def test_is_subscribed_filter_none_container() -> None:
    """Test the IsSubscribed filter when the dishka_container is None."""
    # Arrange
    user = User(id=123, is_bot=False, first_name="Test")
    chat = Chat(id=456, type="private")
    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=chat,
        from_user=user,
        text="/who",
    )
    filter_instance = IsSubscribed()
    data = {"dishka_container": None}

    # Act
    result = await filter_instance(event, **data)

    # Assert
    assert result is False
