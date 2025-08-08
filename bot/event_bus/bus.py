"""Provides the EventBus class for handling event subscriptions and publications."""

import asyncio
from collections import defaultdict
import logging
from typing import Any, Type, TypeVar

from bot.event_bus.types import BaseEvent, EventHandler

T_Event = TypeVar("T_Event", bound=BaseEvent)

logger = logging.getLogger(__name__)


class EventBus:
    """A simple asynchronous event bus."""

    def __init__(self) -> None:
        """Initializes the EventBus."""
        self._subscribers: defaultdict[Type[BaseEvent], list[EventHandler[Any]]] = (
            defaultdict(list)
        )
        self.tasks: set[asyncio.Task[Any]] = set()

    def subscribe(
        self, event_type: Type[T_Event], handler: EventHandler[T_Event]
    ) -> None:
        """Subscribes a handler to a specific event type.

        Args:
            event_type: The type of event to subscribe to.
            handler: The asynchronous callable that will handle the event.
        """
        self._subscribers[event_type].append(handler)
        logger.info(
            "Handler %s subscribed to event %s",
            getattr(handler, "__name__", "Unknown Handler"),
            event_type.__name__,
        )

    async def publish(self, event: BaseEvent) -> None:
        """Publishes an event to all subscribed handlers.

        For each handler subscribed to the event's type, an asyncio task is
        created to run it.

        Args:
            event: The event to publish.
        """
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            logger.debug("No handlers for event %s", event_type.__name__)
            return

        logger.info(
            "Publishing event %s to %d handler(s)",
            event_type.__name__,
            len(handlers),
        )
        for handler in handlers:
            task = asyncio.create_task(handler(event))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
