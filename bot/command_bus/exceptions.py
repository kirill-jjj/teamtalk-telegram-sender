"""Custom exceptions for the Command Bus system."""


class CommandBusError(Exception):
    """Base class for command bus errors."""


class HandlerAlreadyRegisteredError(CommandBusError):
    """Raised when a handler is already registered for a command."""


class NoHandlerFoundError(CommandBusError):
    """Raised when no handler is found for a command."""
