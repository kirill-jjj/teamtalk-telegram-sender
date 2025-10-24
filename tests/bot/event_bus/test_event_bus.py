import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from bot.event_bus.bus import EventBus
from bot.event_bus.types import BaseEvent


class MyEvent(BaseEvent):
    """A dummy event for testing."""

    data: str


class AnotherEvent(BaseEvent):
    """Another dummy event for testing."""

    value: int


@pytest.fixture
def event_bus() -> EventBus:
    """Fixture for an EventBus instance."""
    return EventBus()


@pytest.mark.asyncio
async def test_subscribe_and_publish_event(event_bus: EventBus) -> None:
    """Test successful subscription and publishing of an event."""
    mock_handler = AsyncMock()
    event_bus.subscribe(MyEvent, mock_handler)

    event = MyEvent(data="test_event")
    await event_bus.publish(event)

    # Allow tasks to run
    await asyncio.sleep(0.1)

    mock_handler.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_multiple_handlers_for_same_event(event_bus: EventBus) -> None:
    """Test multiple handlers are called for the same event type."""
    mock_handler1 = AsyncMock()
    mock_handler2 = AsyncMock()
    event_bus.subscribe(MyEvent, mock_handler1)
    event_bus.subscribe(MyEvent, mock_handler2)

    event = MyEvent(data="multiple_handlers")
    await event_bus.publish(event)

    await asyncio.sleep(0.1)

    mock_handler1.assert_called_once_with(event)
    mock_handler2.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_no_handlers_for_event(event_bus: EventBus) -> None:
    """Test publishing an event with no subscribed handlers."""
    mock_handler = AsyncMock()
    event_bus.subscribe(AnotherEvent, mock_handler)  # Subscribe to a different event

    event = MyEvent(data="no_handlers")
    await event_bus.publish(event)

    await asyncio.sleep(0.1)

    mock_handler.assert_not_called()


@pytest.mark.asyncio
async def test_handlers_for_different_event_types(event_bus: EventBus) -> None:
    """Test handlers are called only for their subscribed event types."""
    mock_my_event_handler = AsyncMock()
    mock_another_event_handler = AsyncMock()
    event_bus.subscribe(MyEvent, mock_my_event_handler)
    event_bus.subscribe(AnotherEvent, mock_another_event_handler)

    my_event = MyEvent(data="my_event")
    another_event = AnotherEvent(value=123)

    await event_bus.publish(my_event)
    await event_bus.publish(another_event)

    await asyncio.sleep(0.1)

    mock_my_event_handler.assert_called_once_with(my_event)
    mock_another_event_handler.assert_called_once_with(another_event)


@pytest.mark.asyncio
async def test_tasks_are_discarded_after_completion(event_bus: EventBus) -> None:
    """Test that tasks are removed from the active tasks set after completion."""
    mock_handler = AsyncMock()
    event_bus.subscribe(MyEvent, mock_handler)

    event = MyEvent(data="task_discard")
    await event_bus.publish(event)

    # Wait for the task to complete
    await asyncio.sleep(0.1)

    assert not event_bus.tasks


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_logs_debug(event_bus: EventBus) -> None:
    """Test that publishing an event with no subscribers logs a debug message."""
    with patch("bot.event_bus.bus.logger") as mock_logger:
        event = MyEvent(data="no_subscribers")
        await event_bus.publish(event)
        await asyncio.sleep(0.1)  # Allow tasks to run
        mock_logger.debug.assert_called_once_with("No handlers for event %s", "MyEvent")
