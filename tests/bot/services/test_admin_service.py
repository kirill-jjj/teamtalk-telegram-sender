"""Tests for the AdminService."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from bot.config import (
    DatabaseSettings,
    GeneralSettings,
    Settings,
    TeamTalkSettings,
    TelegramSettings,
)
from bot.database.models import Admin, UserSettings
from bot.database.uow import IUnitOfWork
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
    cache.is_admin = MagicMock(return_value=False)
    return cache


@pytest.fixture
def mock_event_bus() -> AsyncMock:
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    return event_bus


@pytest.fixture
def mock_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.set_my_commands = AsyncMock()
    return bot


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

    result = await admin_service.add_admin(mock_uow, telegram_id)

    assert result.success is True
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.add.assert_called_once_with(Admin(telegram_id=telegram_id))
    mock_cache.add_admin.assert_called_once_with(telegram_id)
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

    result = await admin_service.add_admin(mock_uow, telegram_id)

    assert result.success is True
    assert result.message_key == "admin_add_already_exists"
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.add.assert_not_called()
    mock_cache.add_admin.assert_not_called()
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

    result = await admin_service.remove_admin(mock_uow, telegram_id)

    assert result.success is True
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.delete.assert_called_once_with(mock_admin_obj)
    mock_cache.remove_admin.assert_called_once_with(telegram_id)
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

    result = await admin_service.remove_admin(mock_uow, telegram_id)

    assert result.success is True
    assert result.message_key == "admin_remove_not_exists"
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.delete.assert_not_called()
    mock_cache.remove_admin.assert_not_called()
    mock_event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_add_admin_user_settings_none(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.admins.get_by_id.return_value = None
    mock_uow.users.get_by_id.return_value = None  # UserSettings is None

    result = await admin_service.add_admin(mock_uow, telegram_id)

    assert result.success is True
    mock_uow.admins.add.assert_called_once_with(Admin(telegram_id=telegram_id))
    mock_cache.add_admin.assert_called_once_with(telegram_id)
    mock_event_bus.publish.assert_called_once_with(
        AdminStatusChangedEvent(telegram_id=telegram_id, is_admin=True, lang_code=None)
    )


@pytest.mark.asyncio
async def test_remove_admin_user_settings_none(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_id = 123
    mock_admin_obj = Admin(telegram_id=telegram_id)
    mock_uow.admins.get_by_id.return_value = mock_admin_obj
    mock_uow.users.get_by_id.return_value = None  # UserSettings is None

    result = await admin_service.remove_admin(mock_uow, telegram_id)

    assert result.success is True
    mock_uow.admins.delete.assert_called_once_with(mock_admin_obj)
    mock_cache.remove_admin.assert_called_once_with(telegram_id)
    mock_event_bus.publish.assert_called_once_with(
        AdminStatusChangedEvent(telegram_id=telegram_id, is_admin=False, lang_code=None)
    )


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

    result = await admin_service.add_admins_in_batch(mock_uow, telegram_ids)

    assert sorted(result.successful_ids) == [101, 102, 103]
    assert result.failed_ids == []
    expected_calls = 2
    assert mock_uow.admins.add.call_count == expected_calls
    assert mock_cache.add_admin.call_count == expected_calls
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

    result = await admin_service.remove_admins_in_batch(mock_uow, telegram_ids)

    assert sorted(result.successful_ids) == [201, 202, 203]
    assert result.failed_ids == []
    expected_calls = 2
    assert mock_uow.admins.delete.call_count == expected_calls
    assert mock_cache.remove_admin.call_count == expected_calls
    assert mock_event_bus.publish.call_count == expected_calls


@pytest.mark.asyncio
async def test_add_admins_in_batch_sqlalchemy_error(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_ids = [101, 102]
    mock_uow.admins.get_by_id.side_effect = [None, None]
    mock_uow.admins.add.side_effect = [None, SQLAlchemyError("DB Error")]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=101, language_code="en"),
        UserSettings(telegram_id=102, language_code="en"),
    ]

    result = await admin_service.add_admins_in_batch(mock_uow, telegram_ids)

    assert result.successful_ids == [101]
    assert result.failed_ids == [102]
    assert mock_uow.admins.add.call_count == 2
    assert mock_cache.add_admin.call_count == 1
    assert mock_event_bus.publish.call_count == 1


@pytest.mark.asyncio
async def test_remove_admins_in_batch_sqlalchemy_error(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_ids = [201, 202]
    mock_admin_201 = Admin(telegram_id=201)
    mock_admin_202 = Admin(telegram_id=202)
    mock_uow.admins.get_by_id.side_effect = [mock_admin_201, mock_admin_202]
    mock_uow.admins.delete.side_effect = [None, SQLAlchemyError("DB Error")]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=201, language_code="en"),
        UserSettings(telegram_id=202, language_code="en"),
    ]

    result = await admin_service.remove_admins_in_batch(mock_uow, telegram_ids)

    assert result.successful_ids == [201]
    assert result.failed_ids == [202]
    assert mock_uow.admins.delete.call_count == 2
    assert mock_cache.remove_admin.call_count == 1
    assert mock_event_bus.publish.call_count == 1


@pytest.mark.asyncio
async def test_update_admins_add_success(
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

    result = await admin_service.update_admins(
        mock_uow,
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


@pytest.mark.asyncio
async def test_update_admins_remove_success(
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

    result = await admin_service.update_admins(
        mock_uow,
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


@pytest.mark.asyncio
async def test_update_admins_mixed_add_remove(
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

    result = await admin_service.update_admins(
        mock_uow,
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
    assert mock_uow.admins.add.call_count == expected_add_calls
    assert mock_uow.admins.delete.call_count == expected_delete_calls


@pytest.mark.asyncio
async def test_update_admins_invalid_args(
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

    result = await admin_service.update_admins(
        mock_uow,
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


@pytest.mark.asyncio
async def test_ensure_main_admin_exists_no_admin_chat_id(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_bot: AsyncMock,
) -> None:
    admin_service._settings.telegram.admin_chat_id = None

    await admin_service.ensure_main_admin_exists(mock_uow, mock_bot, MagicMock())

    mock_uow.admins.get_by_id.assert_not_called()
    mock_cache.add_admin.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_main_admin_exists_already_exists_in_db_and_cache(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_bot: AsyncMock,
) -> None:
    telegram_id = admin_service._settings.telegram.admin_chat_id
    mock_uow.admins.get_by_id.return_value = Admin(telegram_id=telegram_id)
    mock_cache.is_admin.return_value = True
    mock_uow.users.get_or_create.return_value = UserSettings(
        telegram_id=telegram_id, language_code="en"
    )
    mock_translator_factory = MagicMock()
    mock_translator_factory.return_value.gettext.return_value = "mocked description"
    await admin_service.ensure_main_admin_exists(
        mock_uow, mock_bot, mock_translator_factory
    )

    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.add.assert_not_called()
    mock_cache.is_admin.assert_called_with(telegram_id)
    assert mock_cache.is_admin.call_count == 2
    mock_cache.add_admin.assert_not_called()
    mock_uow.users.get_or_create.assert_called_once_with(
        telegram_id,
        defaults={"language_code": admin_service._settings.general.default_lang},
    )
    mock_bot.set_my_commands.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_main_admin_exists_in_db_not_in_cache(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_bot: AsyncMock,
) -> None:
    telegram_id = admin_service._settings.telegram.admin_chat_id
    mock_uow.admins.get_by_id.return_value = Admin(telegram_id=telegram_id)
    mock_cache.is_admin.return_value = False
    mock_uow.users.get_or_create.return_value = UserSettings(
        telegram_id=telegram_id, language_code="en"
    )
    mock_translator_factory = MagicMock()
    mock_translator_factory.return_value.gettext.return_value = "mocked description"
    await admin_service.ensure_main_admin_exists(
        mock_uow, mock_bot, mock_translator_factory
    )

    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.add.assert_not_called()
    mock_cache.is_admin.assert_called_with(telegram_id)
    assert mock_cache.is_admin.call_count == 2
    mock_cache.add_admin.assert_called_once_with(telegram_id)
    mock_uow.users.get_or_create.assert_called_once_with(
        telegram_id,
        defaults={"language_code": admin_service._settings.general.default_lang},
    )
    mock_bot.set_my_commands.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_main_admin_exists_not_in_db_newly_created(
    admin_service: AdminService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_bot: AsyncMock,
) -> None:
    telegram_id = admin_service._settings.telegram.admin_chat_id
    mock_uow.admins.get_by_id.return_value = None
    mock_uow.users.get_or_create.return_value = UserSettings(
        telegram_id=telegram_id, language_code="en"
    )
    mock_translator_factory = MagicMock()
    mock_translator_factory.return_value.gettext.return_value = "mocked description"
    await admin_service.ensure_main_admin_exists(
        mock_uow, mock_bot, mock_translator_factory
    )

    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.add.assert_called_once_with(Admin(telegram_id=telegram_id))
    mock_cache.is_admin.assert_called_once_with(
        telegram_id
    )  # Called once inside update_user_bot_commands
    mock_cache.add_admin.assert_called_once_with(telegram_id)
    mock_uow.users.get_or_create.assert_called_once_with(
        telegram_id,
        defaults={"language_code": admin_service._settings.general.default_lang},
    )
    mock_bot.set_my_commands.assert_called_once()  # Checks update_user_bot_commands


@pytest.mark.asyncio
async def test_update_admins_empty_args(
    admin_service: AdminService,
    mock_uow: AsyncMock,
) -> None:
    result = await admin_service.update_admins(
        mock_uow,
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


def test_is_main_teamtalk_admin_no_admin_username(admin_service: AdminService) -> None:
    admin_service._settings.general.admin_username = None
    assert admin_service.is_main_teamtalk_admin("some_user") is False

    admin_service._settings.general.admin_username = ""
    assert admin_service.is_main_teamtalk_admin("some_user") is False


def test_is_main_teamtalk_admin_match(admin_service: AdminService) -> None:
    admin_service._settings.general.admin_username = "test_admin"
    assert admin_service.is_main_teamtalk_admin("test_admin") is True


def test_is_main_teamtalk_admin_no_match(admin_service: AdminService) -> None:
    admin_service._settings.general.admin_username = "test_admin"
    assert admin_service.is_main_teamtalk_admin("other_user") is False
