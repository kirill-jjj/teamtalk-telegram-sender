"""Tests for the report service."""

from gettext import NullTranslations
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.commands import GetAllTeamTalkAccountsResult, GetOnlineUsersResult
from bot.models import BanList, MuteListMode, SubscribedUser, UserSettings
from bot.services.report_service import ReportService
from bot.services.schemas import UserAccountInfo, UserDTO


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.teamtalk.host_name = "TestServer"
    return settings


@pytest.fixture
def mock_uow() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_command_bus() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_translator() -> MagicMock:
    translator = MagicMock(spec=NullTranslations)
    translator.gettext.side_effect = lambda s: s
    translator.ngettext.side_effect = lambda s, p, n: s if n == 1 else p
    return translator


@pytest.fixture
def mock_cache_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_user_settings_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def report_service(
    mock_settings: MagicMock,
    mock_uow: AsyncMock,
    mock_bot: AsyncMock,
    mock_command_bus: AsyncMock,
) -> ReportService:
    return ReportService(mock_settings, mock_uow, mock_bot, mock_command_bus)


@pytest.mark.asyncio
async def test_get_who_report_data_success(
    report_service: ReportService,
    mock_uow: AsyncMock,
    mock_translator: MagicMock,
    mock_cache_service: MagicMock,
    mock_user_settings_service: AsyncMock,
    mock_command_bus: AsyncMock,
) -> None:
    """Test get_who_report_data with a successful result."""
    mock_user_settings_service.get_or_create.return_value = MagicMock(
        language_code="en"
    )
    mock_cache_service.is_admin.return_value = False
    mock_command_bus.execute.return_value = GetOnlineUsersResult(
        success=True,
        users=[
            UserDTO(id=1, nickname="User1", channel_name="Channel1"),
            UserDTO(id=2, nickname="User2", channel_name="Channel1"),
        ],
        server_name="TestServer",
    )

    report = await report_service.get_who_report_data(
        mock_uow,
        123,
        mock_translator,
        mock_cache_service,
        mock_user_settings_service,
        mock_command_bus,
    )

    assert report.error_message is None
    assert report.payload is not None
    assert report.payload.total_users == 2
    assert report.payload.server_name == "TestServer"
    assert len(report.payload.grouped_data) == 1
    assert report.payload.grouped_data[0].channel_name == "Channel1"
    assert len(report.payload.grouped_data[0].users) == 2


@pytest.mark.asyncio
async def test_get_subscribers_info(
    report_service: ReportService, mock_uow: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test get_subscribers_info method."""
    mock_uow.subscribers.count_all.return_value = 1
    mock_uow.subscribers.get_paginated.return_value = [SubscribedUser(telegram_id=123)]
    mock_uow.users.get_by_ids.return_value = [
        UserSettings(telegram_id=123, teamtalk_username="tt_user")
    ]

    monkeypatch.setattr(
        "bot.services.report_service.get_display_names_for_ids",
        AsyncMock(return_value={123: "John Doe"}),
    )

    result = await report_service.get_subscribers_info(mock_uow, page=0)

    assert result.total_items == 1
    assert len(result.items) == 1
    assert result.items[0].telegram_id == 123
    assert result.items[0].display_name == "John Doe"
    assert result.items[0].teamtalk_username == "tt_user"


@pytest.mark.asyncio
async def test_get_banned_users_info(
    report_service: ReportService, mock_uow: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test get_banned_users_info method."""
    mock_uow.bans.count_with_telegram_id.return_value = 1
    mock_uow.bans.get_paginated_with_telegram_id.return_value = [
        BanList(telegram_id=123)
    ]
    mock_uow.users.get_by_ids.return_value = [
        UserSettings(telegram_id=123, teamtalk_username="tt_user")
    ]

    monkeypatch.setattr(
        "bot.services.report_service.get_display_names_for_ids",
        AsyncMock(return_value={123: "Banned User"}),
    )

    result = await report_service.get_banned_users_info(mock_uow, page=0)

    assert result.total_items == 1
    assert len(result.items) == 1
    assert result.items[0].display_name == "Banned User"


@pytest.mark.asyncio
async def test_get_sorted_online_users_for_moderation(
    report_service: ReportService,
    mock_command_bus: AsyncMock,
    mock_user_settings_service: AsyncMock,
) -> None:
    """Test get_sorted_online_users_for_moderation method."""
    mock_user_settings_service.get_or_create.return_value = MagicMock(
        language_code="en"
    )
    mock_command_bus.execute.return_value = GetOnlineUsersResult(
        success=True,
        users=[
            UserDTO(id=2, nickname="UserB", channel_name="Channel1"),
            UserDTO(id=1, nickname="UserA", channel_name="Channel1"),
        ],
        server_name="TestServer",
    )

    result = await report_service.get_sorted_online_users_for_moderation(
        AsyncMock(),
        123,
        MagicMock(),
        MagicMock(),
        mock_user_settings_service,
        mock_command_bus,
    )

    assert len(result.users) == 2
    assert result.users[0].nickname == "UserA"
    assert result.users[1].nickname == "UserB"


@pytest.mark.asyncio
async def test_get_all_server_accounts_view_data(
    report_service: ReportService,
    mock_command_bus: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    """Test get_all_server_accounts_view_data method."""
    mock_command_bus.execute.return_value = GetAllTeamTalkAccountsResult(
        success=True,
        accounts=[UserAccountInfo(username="UserB"), UserAccountInfo(username="UserA")],
    )

    result = await report_service.get_all_server_accounts_view_data(
        "en", mock_translator
    )

    assert len(result.accounts) == 2
    assert result.accounts[0].username == "UserA"
    assert result.accounts[1].username == "UserB"


def test_prepare_mute_list_view_data(
    report_service: ReportService, mock_translator: MagicMock
) -> None:
    """Test prepare_mute_list_view_data method."""
    user_settings = UserSettings(
        mute_list_mode=MuteListMode.blacklist,
        muted_users_list=[
            MagicMock(muted_teamtalk_username="UserB"),
            MagicMock(muted_teamtalk_username="UserA"),
        ],
    )

    result = report_service.prepare_mute_list_view_data(user_settings, mock_translator)

    assert result.title == "Blacklisted Users (Block List)"
    assert result.items == ["UserA", "UserB"]
