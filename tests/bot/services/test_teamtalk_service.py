"""Tests for the TeamTalk service."""

from gettext import NullTranslations
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import Settings, TeamTalkSettings
from bot.services.teamtalk_service import TeamTalkService
from bot.teamtalk_bot.cache import TeamTalkCache
from bot.teamtalk_bot.connection import TeamTalkConnection


@pytest.fixture
def mock_tt_connection() -> AsyncMock:
    conn = AsyncMock(spec=TeamTalkConnection)
    conn.is_ready = True
    conn.ttstr = lambda x: x.decode() if isinstance(x, bytes) else x
    conn.instance = MagicMock()
    conn.cache_manager = MagicMock(spec=TeamTalkCache)
    conn.cache_manager.online_users_cache = {}
    conn.cache_manager.user_accounts_cache = {}
    return conn


@pytest.fixture
def mock_settings() -> Settings:
    settings = MagicMock(spec=Settings)
    settings.teamtalk = MagicMock(spec=TeamTalkSettings)
    settings.teamtalk.host_name = "test_host"
    settings.teamtalk.server_name = "TestServer"
    settings.general = MagicMock()
    settings.general.default_lang = "en"
    return settings


@pytest.fixture
def mock_translator_factory() -> MagicMock:
    translator = MagicMock(spec=NullTranslations)
    translator.gettext.side_effect = lambda x: x
    translator.info.return_value = {"language": "en"}
    return MagicMock(return_value=translator)


@pytest.fixture
def teamtalk_service(
    mock_tt_connection: AsyncMock,
    mock_settings: Settings,
    mock_translator_factory: MagicMock,
) -> TeamTalkService:
    return TeamTalkService(
        tt_connection=mock_tt_connection,
        settings=mock_settings,
        translator_factory=mock_translator_factory,
    )


@pytest.mark.asyncio
async def test_fetch_online_users_success(
    teamtalk_service: TeamTalkService,
    mock_tt_connection: AsyncMock,
) -> None:
    mock_tt_connection.cache_manager.online_users_cache = {
        1: MagicMock(
            id=1,
            nickname="User1",
            username=b"user1",
            channel=MagicMock(name=b"Channel1", id=1),
        ),
        2: MagicMock(
            id=2,
            nickname="User2",
            username=b"user2",
            channel=MagicMock(name=b"Channel1", id=1),
        ),
    }
    mock_tt_connection.ttstr.side_effect = (
        lambda x: x.decode() if isinstance(x, bytes) else x
    )
    mock_tt_connection.instance.get_channel.return_value = MagicMock(name=b"Channel1")

    users, server_name, error_message = await teamtalk_service.fetch_online_users(
        is_caller_admin=False, lang_code="en"
    )

    assert error_message is None
    assert server_name == "TestServer"
    assert len(users) == 2
    assert users[0].nickname == "User1"
    assert users[1].nickname == "User2"


@pytest.mark.asyncio
async def test_fetch_online_users_no_connection(
    teamtalk_service: TeamTalkService,
    mock_tt_connection: AsyncMock,
) -> None:
    mock_tt_connection.is_ready = False

    users, server_name, error_message = await teamtalk_service.fetch_online_users(
        is_caller_admin=False, lang_code="en"
    )

    assert users == []
    assert server_name is None
    assert error_message == "TeamTalk connection is not active."


@pytest.mark.asyncio
async def test_fetch_all_accounts_success(
    teamtalk_service: TeamTalkService,
    mock_tt_connection: AsyncMock,
) -> None:
    mock_tt_connection.cache_manager.user_accounts_cache = {
        "userA": MagicMock(username=b"userA"),
        "userB": MagicMock(username=b"userB"),
    }

    accounts, error_message = await teamtalk_service.fetch_all_accounts(lang_code="en")

    assert error_message is None
    assert len(accounts) == 2
    assert accounts[0].username == "userA"
    assert accounts[1].username == "userB"


@pytest.mark.asyncio
async def test_fetch_all_accounts_no_connection(
    teamtalk_service: TeamTalkService,
    mock_tt_connection: AsyncMock,
) -> None:
    mock_tt_connection.is_ready = False

    accounts, error_message = await teamtalk_service.fetch_all_accounts(lang_code="en")

    assert accounts == []
    assert error_message == "Error: No active TeamTalk connection."


@pytest.mark.asyncio
async def test_fetch_all_accounts_cache_empty(
    teamtalk_service: TeamTalkService,
    mock_tt_connection: AsyncMock,
) -> None:
    mock_tt_connection.cache_manager.user_accounts_cache = {}

    accounts, error_message = await teamtalk_service.fetch_all_accounts(lang_code="en")

    assert accounts == []
    assert error_message == (
        "Server user accounts are not loaded yet. Please try again in a moment."
    )
