import asyncio

from pydantic import BaseModel
import pytest

from bot.command_bus.bus import CommandBus
from bot.command_bus.exceptions import (
    HandlerAlreadyRegisteredError,
    NoHandlerFoundError,
)
from bot.command_bus.types import BaseCommand


class MyCommand(BaseCommand):
    """A dummy command for testing."""

    value: str


class MyResult(BaseModel):
    """A dummy result for testing."""

    message: str


async def my_handler(command: MyCommand) -> MyResult:
    """A dummy handler for testing."""
    await asyncio.sleep(0)
    return MyResult(message=f"Handled: {command.value}")


async def another_handler(command: MyCommand) -> MyResult:
    """Another dummy handler for testing."""
    await asyncio.sleep(0)
    return MyResult(message=f"Another handled: {command.value}")


@pytest.fixture
def command_bus() -> CommandBus:
    """Fixture for a CommandBus instance."""
    return CommandBus()


@pytest.mark.asyncio
async def test_register_and_execute_command(command_bus: CommandBus) -> None:
    """Test successful registration and execution of a command."""
    command_bus.register(MyCommand, my_handler)
    command = MyCommand(value="test_command")
    result = await command_bus.execute(command)

    assert isinstance(result, MyResult)
    assert result.message == "Handled: test_command"


def test_register_handler_already_registered(command_bus: CommandBus) -> None:
    """Test registering a handler for an already registered command type."""
    command_bus.register(MyCommand, my_handler)
    with pytest.raises(HandlerAlreadyRegisteredError):
        command_bus.register(MyCommand, another_handler)


@pytest.mark.asyncio
async def test_execute_no_handler_found(command_bus: CommandBus) -> None:
    """Test executing a command with no registered handler."""
    command = MyCommand(value="test_command")
    with pytest.raises(NoHandlerFoundError):
        await command_bus.execute(command)


@pytest.mark.asyncio
async def test_execute_with_different_command_type(command_bus: CommandBus) -> None:
    """Test executing a command with a different command type."""

    class AnotherCommand(BaseCommand):
        value: int

    async def another_command_handler(command: AnotherCommand) -> MyResult:
        await asyncio.sleep(0)
        return MyResult(message=f"Handled another: {command.value}")

    command_bus.register(AnotherCommand, another_command_handler)
    command = AnotherCommand(value=123)
    result = await command_bus.execute(command)

    assert isinstance(result, MyResult)
    assert result.message == "Handled another: 123"
