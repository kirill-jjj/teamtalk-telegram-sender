"""Tests for the TeamTalkConnection and TeamTalkConnectionManager classes."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytalk
import pytest

from bot.config import GeneralSettings, Settings, TeamTalkSettings
from bot.event_bus.bus import EventBus
from bot.teamtalk_bot.cache import TeamTalkCache
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.connection_manager import TeamTalkConnectionManager
from bot.teamtalk_bot.handlers.pytalk_event_handlers import PytalkEventHandlers


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock(spec=Settings)
    settings.teamtalk = MagicMock(spec=TeamTalkSettings)
    settings.teamtalk.host_name = "test.com"
    settings.teamtalk.port = 10333
    settings.teamtalk.user_name = "test_user"
    settings.teamtalk.password = "test_pass"
    settings.teamtalk.channel = "/Root/Test"
    settings.teamtalk.channel_password = None
    settings.teamtalk.nick_name = "TestBot"
    settings.teamtalk.client_name = "TestClient"
    settings.teamtalk.encrypted = False
    settings.general = MagicMock(spec=GeneralSettings)
    settings.general.gender = "neutral"
    return settings


@pytest.fixture
def mock_event_bus() -> AsyncMock:
    return AsyncMock(spec=EventBus)


@pytest.fixture
def mock_pytalk_bot() -> MagicMock:
    tt_bot = MagicMock(spec=pytalk.TeamTalkBot)
    tt_bot.teamtalks = MagicMock()
    tt_bot.teamtalks.append = MagicMock()
    return tt_bot


@pytest.fixture
def mock_pytalk_event_handlers() -> AsyncMock:
    return AsyncMock(spec=PytalkEventHandlers)


@pytest.fixture
def mock_teamtalk_cache(mock_settings: MagicMock) -> MagicMock:
    cache = MagicMock(spec=TeamTalkCache)
    cache.settings = mock_settings
    cache.stop_background_tasks = AsyncMock()
    return cache


@pytest.fixture
def mock_teamtalk_connection_manager(
    mock_pytalk_bot: MagicMock, mock_pytalk_event_handlers: AsyncMock
) -> MagicMock:
    manager = MagicMock(spec=TeamTalkConnectionManager)
    manager.pytalk_bot = mock_pytalk_bot
    manager.pytalk_event_handlers = mock_pytalk_event_handlers
    manager.connect = MagicMock(return_value=True)
    manager.disconnect_instance = AsyncMock()
    manager.determine_target_channel = AsyncMock(return_value=(1, "/Root/Test"))
    manager.join_configured_channel = AsyncMock()
    return manager


@pytest.fixture
def teamtalk_connection(
    mock_settings: MagicMock,
    mock_event_bus: AsyncMock,
    mock_teamtalk_connection_manager: MagicMock,
    mock_teamtalk_cache: MagicMock,
) -> TeamTalkConnection:
    server_info = pytalk.TeamTalkServerInfo(
        host=mock_settings.teamtalk.host_name,
        tcp_port=mock_settings.teamtalk.port,
        udp_port=mock_settings.teamtalk.port,
        username=mock_settings.teamtalk.user_name,
        password=mock_settings.teamtalk.password,
        encrypted=mock_settings.teamtalk.encrypted,
        nickname=mock_settings.teamtalk.nick_name,
        join_channel_id=0,
        join_channel_password="",
    )
    return TeamTalkConnection(
        server_info=server_info,
        settings=mock_settings,
        event_bus=mock_event_bus,
        connection_manager=mock_teamtalk_connection_manager,
        cache_manager=mock_teamtalk_cache,
    )


@pytest.fixture
def teamtalk_connection_manager(
    mock_pytalk_bot: MagicMock, mock_pytalk_event_handlers: AsyncMock
) -> TeamTalkConnectionManager:
    return TeamTalkConnectionManager(mock_pytalk_bot, mock_pytalk_event_handlers)


# --- TeamTalkConnection Tests ---


def test_teamtalk_connection_init(
    teamtalk_connection: TeamTalkConnection,
    mock_settings: MagicMock,
    mock_event_bus: AsyncMock,
    mock_teamtalk_connection_manager: MagicMock,
    mock_teamtalk_cache: MagicMock,
) -> None:
    assert teamtalk_connection.settings == mock_settings
    assert teamtalk_connection.event_bus == mock_event_bus
    assert teamtalk_connection.connection_manager == mock_teamtalk_connection_manager
    assert teamtalk_connection.cache_manager == mock_teamtalk_cache
    assert teamtalk_connection.instance is None
    assert teamtalk_connection.login_complete_time is None
    assert teamtalk_connection.is_finalized is False
    mock_teamtalk_connection_manager.set_connection.assert_called_once_with(
        teamtalk_connection
    )
    mock_teamtalk_cache.set_connection.assert_called_once_with(teamtalk_connection)


def test_teamtalk_connection_connect(
    teamtalk_connection: TeamTalkConnection,
    mock_teamtalk_connection_manager: MagicMock,
) -> None:
    result = teamtalk_connection.connect()
    assert result is True
    mock_teamtalk_connection_manager.connect.assert_called_once()


@pytest.mark.asyncio
async def test_teamtalk_connection_disconnect_instance(
    teamtalk_connection: TeamTalkConnection,
    mock_teamtalk_connection_manager: MagicMock,
) -> None:
    await teamtalk_connection.disconnect_instance()
    mock_teamtalk_connection_manager.disconnect_instance.assert_called_once()


def test_teamtalk_connection_is_ready(teamtalk_connection: TeamTalkConnection) -> None:
    assert teamtalk_connection.is_ready is False
    teamtalk_connection.instance = MagicMock(spec=pytalk.TeamTalkInstance)
    teamtalk_connection.instance.connected = True
    teamtalk_connection.instance.logged_in = True
    assert teamtalk_connection.is_ready is True


def test_teamtalk_connection_mark_finalized(
    teamtalk_connection: TeamTalkConnection,
) -> None:
    teamtalk_connection.mark_finalized(status=True)
    assert teamtalk_connection.is_finalized is True
    teamtalk_connection.mark_finalized(status=False)
    assert teamtalk_connection.is_finalized is False


# --- TeamTalkConnectionManager Tests ---


def test_teamtalk_connection_manager_init(
    teamtalk_connection_manager: TeamTalkConnectionManager,
    mock_pytalk_bot: MagicMock,
    mock_pytalk_event_handlers: AsyncMock,
) -> None:
    assert teamtalk_connection_manager.pytalk_bot == mock_pytalk_bot
    assert (
        teamtalk_connection_manager.pytalk_event_handlers == mock_pytalk_event_handlers
    )
    assert teamtalk_connection_manager.connection is None


def test_teamtalk_connection_manager_set_connection(
    teamtalk_connection_manager: TeamTalkConnectionManager,
    teamtalk_connection: TeamTalkConnection,
) -> None:
    teamtalk_connection_manager.set_connection(teamtalk_connection)
    assert teamtalk_connection_manager.connection == teamtalk_connection


@pytest.mark.asyncio
async def test_teamtalk_connection_manager_connect_success(
    teamtalk_connection_manager: TeamTalkConnectionManager,
    teamtalk_connection: TeamTalkConnection,
    mock_pytalk_bot: MagicMock,
) -> None:
    teamtalk_connection_manager.set_connection(teamtalk_connection)
    mock_pytalk_instance = MagicMock(spec=pytalk.TeamTalkInstance)
    mock_pytalk_instance.connect.return_value = True
    mock_pytalk_instance.login.return_value = True

    with patch("pytalk.instance.TeamTalkInstance", return_value=mock_pytalk_instance):
        result = teamtalk_connection_manager.connect()

        assert result is True
        assert teamtalk_connection.instance == mock_pytalk_instance
        mock_pytalk_instance.connect.assert_called_once()
        mock_pytalk_instance.login.assert_called_once()
        mock_pytalk_bot.teamtalks.append.assert_called_once_with(mock_pytalk_instance)
        assert teamtalk_connection.is_finalized is False
        assert teamtalk_connection.login_complete_time is None
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_teamtalk_connection_manager_connect_fail(
    teamtalk_connection_manager: TeamTalkConnectionManager,
    teamtalk_connection: TeamTalkConnection,
) -> None:
    teamtalk_connection_manager.set_connection(teamtalk_connection)
    mock_pytalk_instance = MagicMock(spec=pytalk.TeamTalkInstance)
    mock_pytalk_instance.connect.return_value = False  # Simulate connect failure

    with patch("pytalk.instance.TeamTalkInstance", return_value=mock_pytalk_instance):
        result = teamtalk_connection_manager.connect()

        assert result is False
        mock_pytalk_instance.connect.assert_called_once()
        mock_pytalk_instance.login.assert_not_called()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_teamtalk_connection_manager_disconnect_instance(
    teamtalk_connection_manager: TeamTalkConnectionManager,
    teamtalk_connection: TeamTalkConnection,
    mock_teamtalk_cache: MagicMock,
) -> None:
    teamtalk_connection_manager.set_connection(teamtalk_connection)
    teamtalk_connection.instance = MagicMock(spec=pytalk.TeamTalkInstance)
    teamtalk_connection.instance.logged_in = True
    teamtalk_connection.instance.connected = True
    teamtalk_connection.mark_finalized(status=True)
    teamtalk_connection.login_complete_time = datetime.now(UTC)

    await teamtalk_connection_manager.disconnect_instance()

    mock_teamtalk_cache.stop_background_tasks.assert_called_once()
    teamtalk_connection.instance.logout.assert_called_once()
    teamtalk_connection.instance.disconnect.assert_called_once()
    assert teamtalk_connection.is_finalized is False
    assert teamtalk_connection.login_complete_time is None


@pytest.mark.asyncio
async def test_teamtalk_connection_manager_determine_target_channel_by_path(
    teamtalk_connection_manager: TeamTalkConnectionManager,
    teamtalk_connection: TeamTalkConnection,
) -> None:
    teamtalk_connection_manager.set_connection(teamtalk_connection)
    mock_instance = MagicMock(spec=pytalk.TeamTalkInstance)
    mock_channel = MagicMock(spec=pytalk.Channel)
    mock_channel.id = 123
    mock_channel.name = b"Test Channel"
    mock_instance.get_channel_from_path.return_value = mock_channel
    teamtalk_connection.instance = mock_instance
    teamtalk_connection.ttstr = lambda x: x.decode()

    (
        channel_id,
        channel_name,
    ) = await teamtalk_connection_manager.determine_target_channel()

    assert channel_id == 123
    assert channel_name == "Test Channel"
    mock_instance.get_channel_from_path.assert_called_once_with("/Root/Test")


@pytest.mark.asyncio
async def test_teamtalk_connection_manager_determine_target_channel_by_id(
    teamtalk_connection_manager: TeamTalkConnectionManager,
    teamtalk_connection: TeamTalkConnection,
) -> None:
    teamtalk_connection_manager.set_connection(teamtalk_connection)
    teamtalk_connection.settings.teamtalk.channel = "456"  # Set channel to ID
    mock_instance = MagicMock(spec=pytalk.TeamTalkInstance)
    mock_channel = MagicMock(spec=pytalk.Channel)
    mock_channel.id = 456
    mock_channel.name = b"ID Channel"
    mock_instance.get_channel.return_value = mock_channel
    teamtalk_connection.instance = mock_instance
    teamtalk_connection.ttstr = lambda x: x.decode()

    (
        channel_id,
        channel_name,
    ) = await teamtalk_connection_manager.determine_target_channel()

    assert channel_id == 456
    assert channel_name == "ID Channel"
    mock_instance.get_channel.assert_called_once_with(456)


@pytest.mark.asyncio
async def test_teamtalk_connection_manager_join_configured_channel_success(
    teamtalk_connection_manager: TeamTalkConnectionManager,
    teamtalk_connection: TeamTalkConnection,
    mock_pytalk_event_handlers: AsyncMock,
) -> None:
    teamtalk_connection_manager.set_connection(teamtalk_connection)
    mock_instance = MagicMock(spec=pytalk.TeamTalkInstance)
    expected_channel_id = 1
    expected_channel_name = "/Root/Test"
    mock_channel = MagicMock(spec=pytalk.Channel)
    mock_channel.id = expected_channel_id
    mock_channel.name = expected_channel_name.encode()  # pytalk channel name is bytes
    mock_instance.get_channel_from_path.return_value = mock_channel
    teamtalk_connection.instance = mock_instance
    teamtalk_connection.instance.join_channel_by_id = MagicMock()
    teamtalk_connection.ttstr = lambda x: x.decode()

    await teamtalk_connection_manager.join_configured_channel()

    teamtalk_connection.instance.join_channel_by_id.assert_called_once_with(
        1, password=""
    )
    mock_pytalk_event_handlers.finalize_bot_login_sequence.assert_not_called()


@pytest.mark.asyncio
async def test_teamtalk_connection_manager_join_configured_channel_permission_error(
    teamtalk_connection_manager: TeamTalkConnectionManager,
    teamtalk_connection: TeamTalkConnection,
    mock_pytalk_event_handlers: AsyncMock,
) -> None:
    teamtalk_connection_manager.set_connection(teamtalk_connection)
    mock_instance = MagicMock(spec=pytalk.TeamTalkInstance)
    mock_instance.join_channel_by_id.side_effect = pytalk.exceptions.PermissionError(
        "Permission denied"
    )
    mock_instance.getMyCurrentChannelID = MagicMock(return_value=0)  # Root channel
    mock_channel = MagicMock(spec=pytalk.Channel)
    mock_instance.get_channel.return_value = mock_channel
    teamtalk_connection.instance = mock_instance
    teamtalk_connection.ttstr = lambda x: x.decode()

    await teamtalk_connection_manager.join_configured_channel()

    mock_instance.join_channel_by_id.assert_called_once()
    mock_pytalk_event_handlers.finalize_bot_login_sequence.assert_called_once_with(
        mock_channel, teamtalk_connection
    )
