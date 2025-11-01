"""Tests for the TeamTalk-related Dishka providers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytalk
import pytest

from bot.config import Settings, TeamTalkSettings
from bot.di.teamtalk import RequestProvider, TeamTalkProvider
from bot.event_bus.bus import EventBus
from bot.services.teamtalk_command_service import TeamTalkCommandService
from bot.teamtalk_bot.handlers.event_bus_subscribers import TeamTalkReplyHandler
from bot.teamtalk_bot.handlers.message_handlers import (
    PrivateMessageCommandHandlers,
)
from bot.teamtalk_bot.handlers.pytalk_event_handlers import PytalkEventHandlers
from bot.teamtalk_bot.private_message_router import PrivateMessageRouter
from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter

# TeamTalkProvider Tests


def test_get_pytalk_event_handlers() -> None:
    """Test the get_pytalk_event_handlers provider."""
    # Arrange
    event_bus = MagicMock(spec=EventBus)
    translator_factory = MagicMock()
    provider = TeamTalkProvider()

    # Act
    handlers = provider.get_pytalk_event_handlers(event_bus, translator_factory)

    # Assert
    assert isinstance(handlers, PytalkEventHandlers)


@pytest.mark.asyncio
@patch("bot.di.teamtalk.TeamTalkBot")
async def test_get_patched_pytalk_bot(mock_pytalk_bot: MagicMock) -> None:
    """Test the get_patched_pytalk_bot provider."""
    # Arrange
    settings = MagicMock(spec=Settings)
    settings.teamtalk = MagicMock(spec=TeamTalkSettings)
    settings.teamtalk.client_name = "TestClient"
    mock_pytalk_bot.return_value._async_setup_hook = AsyncMock()
    provider = TeamTalkProvider()

    # Act
    bot = await provider.get_patched_pytalk_bot(settings)

    # Assert
    mock_pytalk_bot.assert_called_once_with(client_name="TestClient")
    bot._async_setup_hook.assert_awaited_once()
    assert bot.dispatch is not None


def test_get_connections_dict() -> None:
    """Test the get_connections_dict provider."""
    # Arrange
    provider = TeamTalkProvider()

    # Act
    connections = provider.get_connections_dict()

    # Assert
    assert connections == {}


@pytest.mark.asyncio
@patch("bot.di.teamtalk.TeamTalkConnection")
@patch("bot.di.teamtalk.TeamTalkCache")
@patch("bot.di.teamtalk.TeamTalkConnectionManager")
@patch("asyncio.to_thread")
async def test_get_tt_connection(
    mock_to_thread: AsyncMock,
    _mock_conn_manager: MagicMock,  # noqa: PT019
    _mock_cache: MagicMock,  # noqa: PT019
    mock_connection: MagicMock,
) -> None:
    """Test the get_tt_connection provider."""
    # Arrange
    settings = MagicMock(spec=Settings)
    settings.teamtalk = MagicMock(spec=TeamTalkSettings)
    settings.teamtalk.host_name = "localhost"
    settings.teamtalk.port = 10333
    settings.teamtalk.user_name = "test"
    settings.teamtalk.password = "test"
    settings.teamtalk.encrypted = False
    settings.teamtalk.nick_name = "test_nick"
    settings.teamtalk.channel = "123"
    settings.teamtalk.channel_password = "pass"
    pytalk_bot = MagicMock(spec=pytalk.TeamTalkBot)
    event_bus = MagicMock(spec=EventBus)
    connections = {}
    pytalk_event_handlers = MagicMock(spec=PytalkEventHandlers)
    provider = TeamTalkProvider()
    mock_to_thread.return_value = True
    mock_connection.return_value.disconnect_instance = AsyncMock()

    # Act
    async for conn in provider.get_tt_connection(
        settings,
        pytalk_bot,
        event_bus,
        connections,
        pytalk_event_handlers,
    ):
        # Assert
        assert conn is not None


def test_get_pytalk_event_router() -> None:
    """Test the get_pytalk_event_router provider."""
    # Arrange
    provider = TeamTalkProvider()

    # Act
    router = provider.get_pytalk_event_router(
        MagicMock(), MagicMock(), {}, MagicMock(), MagicMock(), MagicMock()
    )

    # Assert
    assert isinstance(router, PytalkEventRouter)


def test_get_teamtalk_reply_handler() -> None:
    """Test the get_teamtalk_reply_handler provider."""
    # Arrange
    provider = TeamTalkProvider()

    # Act
    handler = provider.get_teamtalk_reply_handler({})

    # Assert
    assert isinstance(handler, TeamTalkReplyHandler)


# RequestProvider Tests


def test_get_message_handler() -> None:
    """Test the get_message_handler provider."""
    # Arrange
    provider = RequestProvider()

    # Act
    handler = provider.get_message_handler(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    # Assert
    assert isinstance(handler, PrivateMessageRouter)


def test_get_tt_command_service() -> None:
    """Test the get_tt_command_service provider."""
    # Arrange
    provider = RequestProvider()

    # Act
    service = provider.get_tt_command_service(
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )

    # Assert
    assert isinstance(service, TeamTalkCommandService)


def test_get_tt_pm_handlers() -> None:
    """Test the get_tt_pm_handlers provider."""
    # Arrange
    provider = RequestProvider()

    # Act
    handlers = provider.get_tt_pm_handlers(MagicMock(spec=TeamTalkCommandService))

    # Assert
    assert isinstance(handlers, PrivateMessageCommandHandlers)
