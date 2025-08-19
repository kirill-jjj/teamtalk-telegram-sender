"""Provides the core types for the command bus system."""

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict

# Using 'Any' as the return type for now, but you could define a BaseResult type
T_Result_co = TypeVar("T_Result_co", bound=Any, covariant=True)
T_Command_contra = TypeVar("T_Command_contra", bound="BaseCommand", contravariant=True)


class BaseCommand(BaseModel):
    """Base class for all commands, ensuring they are Pydantic models."""

    model_config = ConfigDict(arbitrary_types_allowed=True)


class CommandHandler(Protocol[T_Command_contra, T_Result_co]):
    """Defines the protocol for a generic command handler.

    A command handler is an asynchronous callable that accepts a single command
    argument and returns a result.
    """

    async def __call__(self, command: T_Command_contra) -> T_Result_co:
        """Processes an incoming command and returns a result."""
        ...
