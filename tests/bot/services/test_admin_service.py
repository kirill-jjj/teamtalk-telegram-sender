"""Tests for the AdminService."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import (
    DatabaseSettings,
    GeneralSettings,
    Settings,
    TeamTalkSettings,
    TelegramSettings,
)
from bot.database.uow import IUnitOfWork
from bot.models import Admin, UserSettings
from bot.services.admin_service import AdminService
from bot.teamtalk_bot.events import AdminStatusChangedEvent


@pytest.fixture
def mock_uow() -> AsyncMock:
    uow = AsyncMock(spec=IUnitOfWork)
    uow.admins = AsyncMock()
    uow.users = AsyncMock()
    return uow


@pytest.fixture
def mock_cache() -> MagicMock:
    cache = MagicMock()
    cache.add_admin = MagicMock()
    cache.remove_admin = MagicMock()
    return cache


@pytest.fixture
def mock_event_bus() -> AsyncMock:
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    return event_bus


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        general=GeneralSettings(admin_username="test_admin"),
        database=DatabaseSettings(db_file="test.db"),
        telegram=TelegramSettings(
            event_token="test_event_token",
            message_token="test_message_token",
            admin_chat_id=12345,
        ),
        teamtalk=TeamTalkSettings(
            host_name="test.com",
            port=123,
            user_name="bot",
            password="pass",
            channel="/root",
            nick_name="bot",
            client_name="client",
        ),
    )


@pytest.fixture
def admin_service(
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
    mock_settings: Settings,
) -> AdminService:
    return AdminService(
        uow=mock_uow,
        cache=mock_cache,
        event_bus=mock_event_bus,
        settings=mock_settings,
    )


@pytest.mark.asyncio
async def test_add_admin_success(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.admins.get_by_id.return_value = None
    mock_uow.users.get_by_id.return_value = UserSettings(
        telegram_id=telegram_id, language_code="en"
    )

    result = await admin_service.add_admin(telegram_id)

    assert result is True
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.add.assert_called_once_with(Admin(telegram_id=telegram_id))
    mock_cache.add_admin.assert_called_once_with(telegram_id)
    mock_uow.commit.assert_called_once()
    mock_event_bus.publish.assert_called_once_with(
        AdminStatusChangedEvent(telegram_id=telegram_id, is_admin=True, lang_code="en")
    )


@pytest.mark.asyncio
async def test_add_admin_already_exists(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.admins.get_by_id.return_value = Admin(telegram_id=telegram_id)

    result = await admin_service.add_admin(telegram_id)

    assert result is False
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.add.assert_not_called()
    mock_cache.add_admin.assert_not_called()
    mock_uow.commit.assert_not_called()
    mock_event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_remove_admin_success(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_id = 123
    mock_admin_obj = Admin(telegram_id=telegram_id)
    mock_uow.admins.get_by_id.return_value = mock_admin_obj
    mock_uow.users.get_by_id.return_value = UserSettings(
        telegram_id=telegram_id, language_code="en"
    )

    result = await admin_service.remove_admin(telegram_id)

    assert result is True
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.delete.assert_called_once_with(mock_admin_obj)
    mock_cache.remove_admin.assert_called_once_with(telegram_id)
    mock_uow.commit.assert_called_once()
    mock_event_bus.publish.assert_called_once_with(
        AdminStatusChangedEvent(telegram_id=telegram_id, is_admin=False, lang_code="en")
    )


@pytest.mark.asyncio
async def test_remove_admin_not_exists(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.admins.get_by_id.return_value = None

    result = await admin_service.remove_admin(telegram_id)

    assert result is False
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.delete.assert_not_called()
    mock_cache.remove_admin.assert_not_called()
    mock_uow.commit.assert_not_called()
    mock_event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_add_admins_in_batch(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_ids = [101, 102, 103]
    mock_uow.admins.get_by_id.side_effect = [None, Admin(telegram_id=102), None]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=101, language_code="en"),
        UserSettings(telegram_id=102, language_code="en"),
        UserSettings(telegram_id=103, language_code="en"),
    ]

    result = await admin_service.add_admins_in_batch(telegram_ids)

    assert result.successful_ids == [101, 103]
    assert result.failed_ids == [102]
    expected_calls = 2
    assert mock_uow.admins.add.call_count == expected_calls
    assert mock_cache.add_admin.call_count == expected_calls
    assert mock_uow.commit.call_count == expected_calls
    assert mock_event_bus.publish.call_count == expected_calls


@pytest.mark.asyncio
async def test_remove_admins_in_batch(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_ids = [201, 202, 203]
    mock_admin_201 = Admin(telegram_id=201)
    mock_admin_203 = Admin(telegram_id=203)
    mock_uow.admins.get_by_id.side_effect = [mock_admin_201, None, mock_admin_203]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=201, language_code="en"),
        UserSettings(telegram_id=202, language_code="en"),
        UserSettings(telegram_id=203, language_code="en"),
    ]

    result = await admin_service.remove_admins_in_batch(telegram_ids)

    assert result.successful_ids == [201, 203]
    assert result.failed_ids == [202]
    expected_calls = 2
    assert mock_uow.admins.delete.call_count == expected_calls
    assert mock_cache.remove_admin.call_count == expected_calls
    assert mock_uow.commit.call_count == expected_calls
    assert mock_event_bus.publish.call_count == expected_calls


@pytest.mark.asyncio
async def test_manage_admin_ids_add_success(
    admin_service: AdminService,
    mock_uow: AsyncMock,
) -> None:
    add_ids = [101, 102]
    remove_ids = []
    error_messages = []
    mock_uow.admins.get_by_id.side_effect = [None, None]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=101, language_code="en"),
        UserSettings(telegram_id=102, language_code="en"),
    ]

    result = await admin_service.manage_admin_ids(
        add_ids=add_ids,
        remove_ids=remove_ids,
        is_add_action=True,
        error_messages=error_messages,
    )

    assert result.add_result.successful_ids == [101, 102]
    assert not result.add_result.failed_ids
    assert not result.remove_result.successful_ids
    assert not result.remove_result.failed_ids
    assert not result.error_messages
    expected_calls = 2
    assert mock_uow.admins.add.call_count == expected_calls
    assert mock_uow.commit.call_count == expected_calls


@pytest.mark.asyncio
async def test_manage_admin_ids_remove_success(
    admin_service: AdminService,
    mock_uow: AsyncMock,
) -> None:
    add_ids = []
    remove_ids = [201, 202]
    error_messages = []
    mock_admin_201 = Admin(telegram_id=201)
    mock_admin_202 = Admin(telegram_id=202)
    mock_uow.admins.get_by_id.side_effect = [mock_admin_201, mock_admin_202]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=201, language_code="en"),
        UserSettings(telegram_id=202, language_code="en"),
    ]

    result = await admin_service.manage_admin_ids(
        add_ids=add_ids,
        remove_ids=remove_ids,
        is_add_action=False,
        error_messages=error_messages,
    )

    assert not result.add_result.successful_ids
    assert not result.add_result.failed_ids
    assert result.remove_result.successful_ids == [201, 202]
    assert not result.remove_result.failed_ids
    assert not result.error_messages
    expected_calls = 2
    assert mock_uow.admins.delete.call_count == expected_calls
    assert mock_uow.commit.call_count == expected_calls


@pytest.mark.asyncio
async def test_manage_admin_ids_mixed_add_remove(
    admin_service: AdminService,
    mock_uow: AsyncMock,
) -> None:
    add_ids = [101]
    remove_ids = [201]
    error_messages = []
    mock_uow.admins.get_by_id.side_effect = [
        None,
        Admin(telegram_id=201),
    ]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=101, language_code="en"),
        UserSettings(telegram_id=201, language_code="en"),
    ]

    result = await admin_service.manage_admin_ids(
        add_ids=add_ids,
        remove_ids=remove_ids,
        is_add_action=True,
        error_messages=error_messages,
    )

    assert result.add_result.successful_ids == [101]
    assert not result.add_result.failed_ids
    assert result.remove_result.successful_ids == [201]
    assert not result.remove_result.failed_ids
    assert not result.error_messages
    expected_add_calls = 1
    expected_delete_calls = 1
    expected_commit_calls = 2
    assert mock_uow.admins.add.call_count == expected_add_calls
    assert mock_uow.admins.delete.call_count == expected_delete_calls
    assert mock_uow.commit.call_count == expected_commit_calls


@pytest.mark.asyncio
async def test_manage_admin_ids_invalid_args(
    admin_service: AdminService,
    mock_uow: AsyncMock,
) -> None:
    add_ids = [123]
    remove_ids = []
    error_messages = [
        "Invalid Telegram ID to add: abc",
        "Invalid Telegram ID to remove: def",
    ]
    mock_uow.admins.get_by_id.return_value = None
    mock_uow.users.get_by_id.return_value = UserSettings(
        telegram_id=123, language_code="en"
    )

    result = await admin_service.manage_admin_ids(
        add_ids=add_ids,
        remove_ids=remove_ids,
        is_add_action=True,
        error_messages=error_messages,
    )

    assert result.add_result.successful_ids == [123]
    assert not result.add_result.failed_ids
    assert not result.remove_result.successful_ids
    assert not result.remove_result.failed_ids
    assert result.error_messages == [
        "Invalid Telegram ID to add: abc",
        "Invalid Telegram ID to remove: def",
    ]
    assert mock_uow.admins.add.call_count == 1
    assert mock_uow.commit.call_count == 1


@pytest.mark.asyncio
async def test_manage_admin_ids_empty_args(
    admin_service: AdminService,
) -> None:
    result = await admin_service.manage_admin_ids(
        add_ids=[],
        remove_ids=[],
        is_add_action=True,
        error_messages=[],
    )
    assert not result.add_result.successful_ids
    assert not result.add_result.failed_ids
    assert not result.remove_result.successful_ids
    assert not result.remove_result.failed_ids
    assert not result.error_messages
