"""Provides the core types for the event bus system."""

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T_Event = TypeVar("T_Event", bound="BaseEvent", contravariant=True)


class BaseEvent(BaseModel):
    """Base class for all events, ensuring they are Pydantic models."""


class EventHandler(Protocol[T_Event]):
    """Defines the protocol for a generic event handler.

    An event handler is an asynchronous callable that accepts a single event
    argument that is a subtype of BaseEvent.
    """

    async def __call__(self, event: T_Event) -> None:
        """Processes an incoming event."""
        ...
