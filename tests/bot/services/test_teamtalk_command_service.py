"""Tests for the TeamTalkCommandService."""

from gettext import NullTranslations
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.enums import DeeplinkAction
from bot.database.models import Deeplink
from bot.database.uow import IUnitOfWork
from bot.services.admin_service import AdminService
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.schemas import AdminManagementResult, BatchOperationResult
from bot.services.teamtalk_command_service import TeamTalkCommandService


@pytest.fixture
def mock_settings() -> MagicMock:
    """Fixture for mock settings."""
    settings = MagicMock()
    settings.operational_parameters.deeplink_ttl_seconds = 300
    return settings


@pytest.fixture
def mock_cache() -> MagicMock:
    """Fixture for mock cache service."""
    return MagicMock(spec=CacheService)


@pytest.fixture
def mock_deeplink_service() -> AsyncMock:
    """Fixture for mock deeplink service."""
    return AsyncMock(spec=DeeplinkService)


@pytest.fixture
def mock_admin_service() -> AsyncMock:
    """Fixture for mock admin service."""
    return AsyncMock(spec=AdminService)


@pytest.fixture
def mock_uow() -> AsyncMock:
    """Fixture for a mock Unit of Work."""
    return AsyncMock(spec=IUnitOfWork)


@pytest.fixture
def mock_translator() -> MagicMock:
    """Fixture for mock translator."""
    translator = MagicMock(spec=NullTranslations)
    translator.gettext.side_effect = lambda s: s
    return translator


@pytest.fixture
def tt_command_service(
    mock_settings: MagicMock,
    mock_cache: MagicMock,
    mock_deeplink_service: AsyncMock,
    mock_admin_service: AsyncMock,
) -> TeamTalkCommandService:
    """Fixture for TeamTalkCommandService."""
    return TeamTalkCommandService(
        settings=mock_settings,
        cache=mock_cache,
        deeplink_service=mock_deeplink_service,
        admin_service=mock_admin_service,
    )


@pytest.mark.asyncio
async def test_handle_subscribe_success(
    tt_command_service: TeamTalkCommandService,
    mock_uow: AsyncMock,
    mock_deeplink_service: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    """Test successful handling of subscribe command."""
    tt_username = "test_user"
    bot_username = "test_bot"
    mock_deeplink = Deeplink(
        token="test_token", action=DeeplinkAction.SUBSCRIBE, expiry_time=MagicMock()
    )

    mock_deeplink_service.create_deeplink.return_value = mock_deeplink
    mock_cache.get_bot_username.return_value = bot_username

    result = await tt_command_service.handle_subscribe(
        mock_uow, tt_username, mock_translator
    )

    mock_deeplink_service.create_deeplink.assert_called_once()
    assert f"https://t.me/{bot_username}?start={mock_deeplink.token}" in result


@pytest.mark.asyncio
async def test_handle_subscribe_no_bot_username(
    tt_command_service: TeamTalkCommandService,
    mock_uow: AsyncMock,
    mock_deeplink_service: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    """Test handle_subscribe when bot username is not in cache."""
    tt_username = "test_user"
    mock_cache.get_bot_username.return_value = None

    result = await tt_command_service.handle_subscribe(
        mock_uow, tt_username, mock_translator
    )

    mock_deeplink_service.create_deeplink.assert_called_once()
    assert "Could not generate a link" in result


@pytest.mark.asyncio
async def test_handle_unsubscribe_success(
    tt_command_service: TeamTalkCommandService,
    mock_uow: AsyncMock,
    mock_deeplink_service: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    """Test successful handling of unsubscribe command."""
    bot_username = "test_bot"
    mock_deeplink = Deeplink(
        token="test_token", action=DeeplinkAction.UNSUBSCRIBE, expiry_time=MagicMock()
    )
    mock_deeplink_service.create_deeplink.return_value = mock_deeplink
    mock_cache.get_bot_username.return_value = bot_username

    result = await tt_command_service.handle_unsubscribe(mock_uow, mock_translator)

    mock_deeplink_service.create_deeplink.assert_called_once()
    assert f"https://t.me/{bot_username}?start={mock_deeplink.token}" in result


@pytest.mark.asyncio
async def test_handle_admin_update_no_args(
    tt_command_service: TeamTalkCommandService,
    mock_uow: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    """Test handle_admin_update with no arguments string."""
    result = await tt_command_service.handle_admin_update(
        mock_uow, None, mock_translator, is_add_action=True
    )
    assert "Please provide Telegram IDs." in result.error_messages


@pytest.mark.asyncio
async def test_handle_admin_update_calls_service(
    tt_command_service: TeamTalkCommandService,
    mock_uow: AsyncMock,
    mock_admin_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    """Test that handle_admin_update correctly calls the admin service."""
    args_str = "123 -456"
    mock_admin_service.apply_admin_changes.return_value = AdminManagementResult(
        add_result=BatchOperationResult(successful_ids=[123]),
        remove_result=BatchOperationResult(successful_ids=[456]),
        error_messages=[],
    )

    await tt_command_service.handle_admin_update(
        mock_uow, args_str, mock_translator, is_add_action=True
    )

    mock_admin_service.apply_admin_changes.assert_called_once()
    call_args = mock_admin_service.apply_admin_changes.call_args
    assert call_args.kwargs["add_ids"] == [123]
    assert call_args.kwargs["remove_ids"] == [456]
    assert call_args.kwargs["is_add_action"] is True


@pytest.mark.parametrize(
    ("args_string", "expected_add", "expected_remove", "expected_errors"),
    [
        ("123 456", [123, 456], [], []),
        ("-123 -456", [], [123, 456], []),
        (
            "123 -456 abc -def",
            [123],
            [456],
            ["Invalid Telegram ID to add: abc", "Invalid Telegram ID to remove: def"],
        ),
        ("", [], [], []),
    ],
)
def test_parse_admin_ids_args(
    tt_command_service: TeamTalkCommandService,
    mock_translator: MagicMock,
    args_string: str,
    expected_add: list[int],
    expected_remove: list[int],
    expected_errors: list[str],
) -> None:
    """Test the _parse_admin_ids_args static method."""
    mock_translator.gettext.side_effect = lambda s: s.format("{}")

    add_ids, remove_ids, errors = tt_command_service._parse_admin_ids_args(
        args_string, mock_translator
    )

    assert add_ids == expected_add
    assert remove_ids == expected_remove
    # Comparing just the start of the error message to avoid being too brittle
    assert len(errors) == len(expected_errors)
    for i, err in enumerate(errors):
        assert err.startswith(expected_errors[i].split(":")[0])
