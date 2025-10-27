import typing
from unittest.mock import AsyncMock, MagicMock, patch

from dishka import AsyncContainer
import pytalk
from pytalk.channel import Channel as PytalkChannel
from pytalk.message import Message as TeamTalkMessage
from pytalk.server import Server as PytalkServer
from pytalk.user import User as PytalkUser
from pytalk.user_account import UserAccount as PytalkUserAccount
import pytest

from bot.event_bus.bus import EventBus
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.handlers.pytalk_event_handlers import PytalkEventHandlers
from bot.teamtalk_bot.message_handler import MessageHandler
from bot.teamtalk_bot.pytalk_event_router import (
    PytalkEventRouter,
    _get_tt_instance_from_event,
)


@pytest.fixture
def mock_app_container() -> MagicMock:
    """Fixture for a mock AsyncContainer, using MagicMock."""
    return MagicMock(spec=AsyncContainer)


@pytest.fixture
def mock_tt_bot() -> AsyncMock:
    """Fixture for a mock pytalk.TeamTalkBot."""
    tt_bot = AsyncMock(spec=pytalk.TeamTalkBot)
    tt_bot.event = MagicMock(side_effect=lambda func: func)  # Decorator passthrough
    return tt_bot


@pytest.fixture
def mock_event_bus() -> AsyncMock:
    """Fixture for a mock EventBus."""
    return AsyncMock(spec=EventBus)


@pytest.fixture
def mock_translator_factory() -> MagicMock:
    """Fixture for a mock translator_factory."""
    return MagicMock()


@pytest.fixture
def mock_pytalk_event_handlers() -> AsyncMock:
    """Fixture for a mock PytalkEventHandlers."""
    return AsyncMock(spec=PytalkEventHandlers)


@pytest.fixture
def mock_teamtalk_connection() -> AsyncMock:
    """Fixture for a mock TeamTalkConnection."""
    conn = AsyncMock(spec=TeamTalkConnection)
    conn.server_info = MagicMock(spec=pytalk.TeamTalkServerInfo)
    conn.server_info.host = "test_host"
    conn.server_info.tcp_port = 12345
    conn.instance = MagicMock(spec=pytalk.instance.TeamTalkInstance)
    return conn


@pytest.fixture
def mock_connections(
    mock_teamtalk_connection: AsyncMock,
) -> dict[str, TeamTalkConnection]:
    """Fixture for a mock connections dictionary."""
    return {
        f"{mock_teamtalk_connection.server_info.host}:"
        f"{mock_teamtalk_connection.server_info.tcp_port}": mock_teamtalk_connection
    }


@pytest.fixture
def pytalk_event_router(
    mock_app_container: MagicMock,
    mock_tt_bot: AsyncMock,
    mock_connections: dict[str, TeamTalkConnection],
    mock_event_bus: AsyncMock,
    mock_translator_factory: MagicMock,
    mock_pytalk_event_handlers: AsyncMock,
) -> PytalkEventRouter:
    """Fixture for a PytalkEventRouter instance."""
    return PytalkEventRouter(
        app_container=mock_app_container,
        tt_bot=mock_tt_bot,
        connections=mock_connections,
        event_bus=mock_event_bus,
        translator_factory=mock_translator_factory,
        pytalk_event_handlers=mock_pytalk_event_handlers,
    )


# --- Test _get_tt_instance_from_event ---
@pytest.mark.parametrize(
    ("event_obj_attr", "get_expected_instance"),
    [
        ("teamtalk_instance", lambda: MagicMock(spec=pytalk.instance.TeamTalkInstance)),
        (
            "server",
            lambda: MagicMock(
                server=MagicMock(
                    teamtalk_instance=MagicMock(spec=pytalk.instance.TeamTalkInstance)
                )
            ),
        ),
        (
            "teamtalk",
            lambda: MagicMock(
                teamtalk=MagicMock(spec=pytalk.instance.TeamTalkInstance)
            ),
        ),
        ("no_instance", lambda: None),
    ],
)
def test_get_tt_instance_from_event(
    event_obj_attr: str, get_expected_instance: typing.Callable
) -> None:
    """Test _get_tt_instance_from_event extracts instance correctly."""
    expected_instance = get_expected_instance()
    if event_obj_attr == "no_instance":
        event_obj = MagicMock()
        # Ensure it has no relevant attributes
        event_obj.teamtalk_instance = None
        event_obj.server = None
        event_obj.teamtalk = None
    elif event_obj_attr == "teamtalk_instance":
        event_obj = MagicMock(teamtalk_instance=expected_instance)
    elif event_obj_attr == "server":
        event_obj = MagicMock(
            teamtalk_instance=None,
            server=MagicMock(teamtalk_instance=expected_instance),
        )
    elif event_obj_attr == "teamtalk":
        event_obj = MagicMock(
            teamtalk_instance=None,
            server=None,
            teamtalk=expected_instance,
        )
    else:
        event_obj = MagicMock()

    result = _get_tt_instance_from_event(event_obj)
    assert result is expected_instance


# --- Test PytalkEventRouter __init__ and registration ---
@pytest.mark.usefixtures("pytalk_event_router")
def test_pytalk_event_router_init_registers_handlers(mock_tt_bot: AsyncMock) -> None:
    """Test that __init__ registers all expected handlers with tt_bot."""
    expected_handlers = [
        "on_my_login",
        "on_my_connection_lost",
        "on_my_kicked_from_channel",
        "on_message",
        "on_user_login",
        "on_user_join",
        "on_user_logout",
        "on_user_update",
        "on_user_account_new",
        "on_user_account_remove",
    ]
    for handler_name in expected_handlers:
        assert hasattr(mock_tt_bot, handler_name)
        # Check if tt_bot.event was called with the correct handler method
        # Check if tt_bot.event was called with a callable (the decorated method)
        found = False
        for call_arg in mock_tt_bot.event.call_args_list:
            if callable(call_arg.args[0]):
                found = True
                break
        assert found, f"mock_tt_bot.event not called with a callable for {handler_name}"


# --- Test _get_connection_by_instance ---
def test_get_connection_by_instance_found(
    pytalk_event_router: PytalkEventRouter, mock_teamtalk_connection: AsyncMock
) -> None:
    """Test _get_connection_by_instance returns the correct connection."""
    result = pytalk_event_router._get_connection_by_instance(
        mock_teamtalk_connection.instance
    )
    assert result is mock_teamtalk_connection


def test_get_connection_by_instance_not_found(
    pytalk_event_router: PytalkEventRouter,
) -> None:
    """Test _get_connection_by_instance returns None if not found."""
    mock_instance = MagicMock(spec=pytalk.instance.TeamTalkInstance)
    result = pytalk_event_router._get_connection_by_instance(mock_instance)
    assert result is None


# --- Test _get_connection_by_server_info ---
def test_get_connection_by_server_info_found(
    pytalk_event_router: PytalkEventRouter, mock_teamtalk_connection: AsyncMock
) -> None:
    """Test _get_connection_by_server_info returns the correct connection."""
    result = pytalk_event_router._get_connection_by_server_info(
        mock_teamtalk_connection.server_info
    )
    assert result is mock_teamtalk_connection


def test_get_connection_by_server_info_not_found(
    pytalk_event_router: PytalkEventRouter,
) -> None:
    """Test _get_connection_by_server_info returns None if not found."""
    mock_server_info = MagicMock(spec=pytalk.TeamTalkServerInfo)
    mock_server_info.host = "unknown_host"
    mock_server_info.tcp_port = 9999
    result = pytalk_event_router._get_connection_by_server_info(mock_server_info)
    assert result is None


# --- Test decorated event handlers ---
@pytest.mark.asyncio
async def test_on_pytalk_my_login_routes_to_handler(
    pytalk_event_router: PytalkEventRouter,
    mock_pytalk_event_handlers: AsyncMock,
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_my_login routes to pytalk_event_handlers.on_my_login."""
    mock_server = MagicMock(spec=PytalkServer)
    mock_server.teamtalk_instance = mock_teamtalk_connection.instance

    await pytalk_event_router.on_pytalk_my_login(mock_server)
    mock_pytalk_event_handlers.on_my_login.assert_called_once_with(
        mock_server, mock_teamtalk_connection
    )


@pytest.mark.asyncio
async def test_on_pytalk_user_join_routes_to_handler(
    pytalk_event_router: PytalkEventRouter,
    mock_pytalk_event_handlers: AsyncMock,
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_user_join routes to pytalk_event_handlers.on_user_join."""
    mock_user = MagicMock(spec=PytalkUser)
    mock_user.teamtalk_instance = mock_teamtalk_connection.instance
    mock_channel = MagicMock(spec=PytalkChannel)

    await pytalk_event_router.on_pytalk_user_join(mock_user, mock_channel)
    mock_pytalk_event_handlers.on_user_join.assert_called_once_with(
        mock_user, mock_channel, mock_teamtalk_connection
    )


@pytest.mark.asyncio
async def test_on_pytalk_my_connection_lost_routes_to_handler(
    pytalk_event_router: PytalkEventRouter,
    mock_pytalk_event_handlers: AsyncMock,
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_my_connection_lost routes to
    pytalk_event_handlers.on_my_connection_lost."""
    mock_server = MagicMock(spec=PytalkServer)
    mock_server.info = mock_teamtalk_connection.server_info  # For special case handling
    mock_server.teamtalk_instance = mock_teamtalk_connection.instance

    await pytalk_event_router.on_pytalk_my_connection_lost(mock_server)
    mock_pytalk_event_handlers.on_my_connection_lost.assert_called_once_with(
        mock_server, mock_teamtalk_connection
    )


@pytest.mark.asyncio
async def test_on_pytalk_my_connection_lost_no_instance_but_server_info(
    pytalk_event_router: PytalkEventRouter,
    mock_pytalk_event_handlers: AsyncMock,
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_my_connection_lost handles no instance but valid server_info."""
    mock_server = MagicMock(spec=PytalkServer)
    mock_server.info = mock_teamtalk_connection.server_info
    mock_server.teamtalk_instance = None  # Simulate instance being gone

    await pytalk_event_router.on_pytalk_my_connection_lost(mock_server)
    mock_pytalk_event_handlers.on_my_connection_lost.assert_called_once_with(
        mock_server, mock_teamtalk_connection
    )


@pytest.mark.asyncio
async def test_on_pytalk_message_routes_to_message_handler(
    pytalk_event_router: PytalkEventRouter,
    mock_app_container: MagicMock,  # Changed to MagicMock
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_message routes to MessageHandler.route_message."""
    mock_message = MagicMock(spec=TeamTalkMessage)
    mock_message.teamtalk_instance = mock_teamtalk_connection.instance

    mock_message_handler = AsyncMock(spec=MessageHandler)

    # Correctly mock the async context manager
    mock_request_container = AsyncMock()
    mock_request_container.get.return_value = mock_message_handler

    async_context_manager_mock = AsyncMock()
    async_context_manager_mock.__aenter__.return_value = mock_request_container
    mock_app_container.return_value = async_context_manager_mock

    await pytalk_event_router.on_pytalk_message(mock_message)

    # Verify that the container was used to get the handler
    mock_app_container.assert_called_once()
    call_args, call_kwargs = mock_app_container.call_args
    assert not call_args
    assert "context" in call_kwargs
    context_arg = call_kwargs["context"]
    assert context_arg[TeamTalkMessage] is mock_message
    assert context_arg[TeamTalkConnection] is mock_teamtalk_connection

    # Verify that the handler's method was called
    mock_message_handler.route_message.assert_called_once_with(mock_message)


@pytest.mark.asyncio
async def test_on_pytalk_user_login_routes_to_handler(
    pytalk_event_router: PytalkEventRouter,
    mock_pytalk_event_handlers: AsyncMock,
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_user_login routes to pytalk_event_handlers.on_user_login."""
    mock_user = MagicMock(spec=PytalkUser)
    mock_user.teamtalk_instance = mock_teamtalk_connection.instance

    await pytalk_event_router.on_pytalk_user_login(mock_user)
    mock_pytalk_event_handlers.on_user_login.assert_called_once_with(
        mock_user, mock_teamtalk_connection
    )


@pytest.mark.asyncio
async def test_on_pytalk_user_logout_routes_to_handler(
    pytalk_event_router: PytalkEventRouter,
    mock_pytalk_event_handlers: AsyncMock,
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_user_logout routes to pytalk_event_handlers.on_user_logout."""
    mock_user = MagicMock(spec=PytalkUser)
    mock_user.teamtalk_instance = mock_teamtalk_connection.instance

    await pytalk_event_router.on_pytalk_user_logout(mock_user)
    mock_pytalk_event_handlers.on_user_logout.assert_called_once_with(
        mock_user, mock_teamtalk_connection
    )


@pytest.mark.asyncio
async def test_on_pytalk_user_update_routes_to_handler(
    pytalk_event_router: PytalkEventRouter,
    mock_pytalk_event_handlers: AsyncMock,
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_user_update routes to pytalk_event_handlers.on_user_update."""
    mock_user = MagicMock(spec=PytalkUser)
    mock_user.teamtalk_instance = mock_teamtalk_connection.instance

    await pytalk_event_router.on_pytalk_user_update(mock_user)
    mock_pytalk_event_handlers.on_user_update.assert_called_once_with(
        mock_user, mock_teamtalk_connection
    )


@pytest.mark.asyncio
async def test_on_pytalk_user_account_new_routes_to_handler(
    pytalk_event_router: PytalkEventRouter,
    mock_pytalk_event_handlers: AsyncMock,
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_user_account_new routes to
    pytalk_event_handlers.on_user_account_new."""
    mock_account = MagicMock(spec=PytalkUserAccount)
    mock_account.teamtalk_instance = mock_teamtalk_connection.instance

    await pytalk_event_router.on_pytalk_user_account_new(mock_account)
    mock_pytalk_event_handlers.on_user_account_new.assert_called_once_with(
        mock_account, mock_teamtalk_connection
    )


@pytest.mark.asyncio
async def test_on_pytalk_user_account_remove_routes_to_handler(
    pytalk_event_router: PytalkEventRouter,
    mock_pytalk_event_handlers: AsyncMock,
    mock_teamtalk_connection: AsyncMock,
) -> None:
    """Test on_pytalk_user_account_remove routes to
    pytalk_event_handlers.on_user_account_remove."""
    mock_account = MagicMock(spec=PytalkUserAccount)
    mock_account.teamtalk_instance = mock_teamtalk_connection.instance

    await pytalk_event_router.on_pytalk_user_account_remove(mock_account)
    mock_pytalk_event_handlers.on_user_account_remove.assert_called_once_with(
        mock_account, mock_teamtalk_connection
    )


@pytest.mark.asyncio
async def test_decorator_logs_error_if_no_tt_instance(
    pytalk_event_router: PytalkEventRouter,
) -> None:
    """Test that the decorator logs an error if no tt_instance is found."""
    with (
        patch(
            "bot.teamtalk_bot.pytalk_event_router._get_tt_instance_from_event",
            return_value=None,
        ),
        patch.object(pytalk_event_router.logger, "error") as mock_log_error,
    ):
        mock_server = MagicMock(spec=PytalkServer)
        await pytalk_event_router.on_pytalk_my_login(mock_server)
        mock_log_error.assert_called_once()
        assert (
            "Decorator: No TT instance for evt type" in mock_log_error.call_args[0][0]
        )


@pytest.mark.asyncio
async def test_decorator_logs_warning_if_no_connection_found(
    pytalk_event_router: PytalkEventRouter,
) -> None:
    """Test that the decorator logs a warning if no TeamTalkConnection is found."""
    mock_instance = MagicMock(spec=pytalk.instance.TeamTalkInstance)
    mock_event_obj = MagicMock(teamtalk_instance=mock_instance)

    # Simulate _get_connection_by_instance returning None
    with (
        patch.object(
            pytalk_event_router, "_get_connection_by_instance", return_value=None
        ),
        patch.object(pytalk_event_router.logger, "warning") as mock_log_warning,
    ):
        await pytalk_event_router.on_pytalk_my_login(mock_event_obj)
        mock_log_warning.assert_called_once()
        assert (
            "Decorator: No active TTConnection for instance"
            in mock_log_warning.call_args[0][0]
        )
