"""Provides the CommandBus class for handling command registration and execution."""

from collections.abc import Callable, Coroutine
import logging
from typing import Any, cast

from bot.command_bus.exceptions import (
    HandlerAlreadyRegisteredError,
    NoHandlerFoundError,
)
from bot.command_bus.types import (
    BaseCommand,
    T_Command_contra,
    T_Result_co,
)

logger = logging.getLogger(__name__)

# A generic callable that takes a command and returns a coroutine.
# This is used for type hinting the handlers in the bus.
HandlerCallable = Callable[[Any], Coroutine[Any, Any, Any]]


class CommandBus:
    """A simple asynchronous command bus."""

    def __init__(self) -> None:
        """Initializes the CommandBus."""
        self._handlers: dict[type[BaseCommand], HandlerCallable] = {}

    def register(
        self,
        command_type: type[T_Command_contra],
        handler: HandlerCallable,
    ) -> None:
        """Registers a handler for a specific command type.

        Args:
            command_type: The type of command to register.
            handler: The asynchronous callable that will handle the command.

        Raises:
            HandlerAlreadyRegisteredError: If a handler for this command type is
                already registered.
        """
        if command_type in self._handlers:
            raise HandlerAlreadyRegisteredError

        self._handlers[command_type] = handler
        logger.info(
            "Handler %s registered for command %s",
            getattr(handler, "__name__", "Unknown Handler"),
            command_type.__name__,
        )

    async def execute(self, command: BaseCommand) -> T_Result_co:
        """Executes a command by finding and running its registered handler.

        Args:
            command: The command to execute.

        Returns:
            The result from the command handler.

        Raises:
            NoHandlerFoundError: If no handler is found for the given command.
        """
        command_type = type(command)
        handler = self._handlers.get(command_type)

        if not handler:
            logger.error("No handler found for command %s", command_type.__name__)
            raise NoHandlerFoundError

        logger.debug(
            "Executing command %s with handler %s",
            command_type.__name__,
            getattr(handler, "__name__", "..."),
        )
        # We cast here because the type of the handler's result is erased
        # in the generic CommandBus, but known by the caller.
        return cast(T_Result_co, await handler(command))
