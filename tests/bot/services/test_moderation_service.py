from gettext import NullTranslations
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.enums import UserListAction
from bot.database.uow import IUnitOfWork  # Import IUnitOfWork
from bot.models import Admin, UserSettings
from bot.services.moderation_service import ModerationService
from bot.teamtalk_bot.events import AdminStatusChangedEvent


@pytest.fixture
def mock_uow() -> AsyncMock:
    uow = AsyncMock(spec=IUnitOfWork)  # Use spec for Pydantic validation
    uow.admins = AsyncMock()
    uow.users = AsyncMock()
    uow.bans = AsyncMock()
    return uow


@pytest.fixture
def mock_subscription_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_cache() -> MagicMock:
    cache = MagicMock()
    cache.add_admin = MagicMock()
    cache.remove_admin = MagicMock()
    cache.update_user_settings = MagicMock()
    return cache


@pytest.fixture
def mock_event_bus() -> AsyncMock:
    event_bus = AsyncMock()
    event_bus.publish = AsyncMock()
    return event_bus


@pytest.fixture
def mock_command_bus() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_translator() -> MagicMock:
    translator = MagicMock(spec=NullTranslations)
    translator.gettext.side_effect = lambda x: x  # Simple passthrough for testing
    translator.ngettext.side_effect = (
        lambda s, p, n: s if n == 1 else p
    )  # Simple pluralization for testing
    translator.info.return_value = {"language": "en"}
    return translator


@pytest.fixture
def moderation_service(
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
    mock_command_bus: AsyncMock,
) -> ModerationService:
    return ModerationService(
        uow=mock_uow,
        subscription_service=mock_subscription_service,
        cache=mock_cache,
        event_bus=mock_event_bus,
        command_bus=mock_command_bus,
    )


@pytest.mark.asyncio
async def test_add_admin_success(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.admins.get_by_id.return_value = None
    mock_uow.users.get_by_id.return_value = UserSettings(
        telegram_id=telegram_id, language_code="en"
    )

    result = await moderation_service.add_admin(telegram_id)

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
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.admins.get_by_id.return_value = Admin(telegram_id=telegram_id)

    result = await moderation_service.add_admin(telegram_id)

    assert result is False
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.add.assert_not_called()
    mock_cache.add_admin.assert_not_called()
    mock_uow.commit.assert_not_called()
    mock_event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_remove_admin_success(
    moderation_service: ModerationService,
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

    result = await moderation_service.remove_admin(telegram_id)

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
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_id = 123
    mock_uow.admins.get_by_id.return_value = None

    result = await moderation_service.remove_admin(telegram_id)

    assert result is False
    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.admins.delete.assert_not_called()
    mock_cache.remove_admin.assert_not_called()
    mock_uow.commit.assert_not_called()
    mock_event_bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_add_admins_in_batch(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_ids = [101, 102, 103]
    # Simulate 101 success, 102 already exists, 103 success
    mock_uow.admins.get_by_id.side_effect = [None, Admin(telegram_id=102), None]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=101, language_code="en"),
        UserSettings(telegram_id=102, language_code="en"),
        UserSettings(telegram_id=103, language_code="en"),
    ]

    result = await moderation_service.add_admins_in_batch(telegram_ids)

    assert result.successful_ids == [101, 103]
    assert result.failed_ids == [102]
    expected_calls = 2
    assert mock_uow.admins.add.call_count == expected_calls
    assert mock_cache.add_admin.call_count == expected_calls
    assert mock_uow.commit.call_count == expected_calls  # Each add_admin commits
    assert mock_event_bus.publish.call_count == expected_calls


@pytest.mark.asyncio
async def test_remove_admins_in_batch(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_event_bus: AsyncMock,
) -> None:
    telegram_ids = [201, 202, 203]
    # Simulate 201 success, 202 not exists, 203 success
    mock_admin_201 = Admin(telegram_id=201)
    mock_admin_203 = Admin(telegram_id=203)
    mock_uow.admins.get_by_id.side_effect = [mock_admin_201, None, mock_admin_203]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=201, language_code="en"),
        UserSettings(telegram_id=202, language_code="en"),
        UserSettings(telegram_id=203, language_code="en"),
    ]

    result = await moderation_service.remove_admins_in_batch(telegram_ids)

    assert result.successful_ids == [201, 203]
    assert result.failed_ids == [202]
    expected_calls = 2
    assert mock_uow.admins.delete.call_count == expected_calls
    assert mock_cache.remove_admin.call_count == expected_calls
    assert mock_uow.commit.call_count == expected_calls  # Each remove_admin commits
    assert mock_event_bus.publish.call_count == expected_calls


@pytest.mark.asyncio
async def test_manage_admin_ids_add_success(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    add_ids = [101, 102]
    remove_ids = []
    error_messages = []
    mock_uow.admins.get_by_id.side_effect = [None, None]
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=101, language_code="en"),
        UserSettings(telegram_id=102, language_code="en"),
    ]

    result = await moderation_service.manage_admin_ids(
        add_ids=add_ids,
        remove_ids=remove_ids,
        is_add_action=True,
        error_messages=error_messages,
        translator=mock_translator,
    )

    assert "Successfully added 2 admins." in result
    expected_calls = 2
    assert mock_uow.admins.add.call_count == expected_calls
    assert mock_uow.commit.call_count == expected_calls


@pytest.mark.asyncio
async def test_manage_admin_ids_remove_success(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_translator: MagicMock,
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

    result = await moderation_service.manage_admin_ids(
        add_ids=add_ids,
        remove_ids=remove_ids,
        is_add_action=False,
        error_messages=error_messages,
        translator=mock_translator,
    )

    assert "Successfully removed 2 admins." in result
    expected_calls = 2
    assert mock_uow.admins.delete.call_count == expected_calls
    assert mock_uow.commit.call_count == expected_calls


@pytest.mark.asyncio
async def test_manage_admin_ids_mixed_add_remove(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    add_ids = [101]
    remove_ids = [201]
    error_messages = []
    mock_uow.admins.get_by_id.side_effect = [
        None,
        Admin(telegram_id=201),
    ]  # 101 is new, 201 exists
    mock_uow.users.get_by_id.side_effect = [
        UserSettings(telegram_id=101, language_code="en"),
        UserSettings(telegram_id=201, language_code="en"),
    ]

    result = await moderation_service.manage_admin_ids(
        add_ids=add_ids,
        remove_ids=remove_ids,
        is_add_action=True,
        error_messages=error_messages,
        translator=mock_translator,
    )

    assert "Successfully added 1 admins." in result
    assert "Successfully removed 1 admins." in result
    assert mock_uow.admins.add.call_count == 1
    assert mock_uow.admins.delete.call_count == 1
    expected_commit_calls = 2
    assert mock_uow.commit.call_count == expected_commit_calls


@pytest.mark.asyncio
async def test_manage_admin_ids_invalid_args(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    add_ids = [123]
    remove_ids = []
    error_messages = [
        "Invalid Telegram ID to add: abc",
        "Invalid Telegram ID to remove: def",
    ]
    mock_uow.admins.get_by_id.return_value = None  # For 123
    mock_uow.users.get_by_id.return_value = UserSettings(
        telegram_id=123, language_code="en"
    )

    result = await moderation_service.manage_admin_ids(
        add_ids=add_ids,
        remove_ids=remove_ids,
        is_add_action=True,
        error_messages=error_messages,
        translator=mock_translator,
    )

    assert "Invalid Telegram ID to add: abc" in result
    assert "Invalid Telegram ID to remove: def" in result
    assert "Successfully added 1 admins." in result
    assert mock_uow.admins.add.call_count == 1
    assert mock_uow.commit.call_count == 1


@pytest.mark.asyncio
async def test_manage_admin_ids_empty_args(
    moderation_service: ModerationService, mock_translator: MagicMock
) -> None:
    result = await moderation_service.manage_admin_ids(
        add_ids=[],
        remove_ids=[],
        is_add_action=True,
        error_messages=[],
        translator=mock_translator,
    )
    assert "No valid admin IDs provided for adding or removing." in result


@pytest.mark.asyncio
async def test_ban_subscriber_success(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    mock_user_settings = UserSettings(
        telegram_id=telegram_id, teamtalk_username="test_tt_user"
    )
    mock_uow.users.get_by_id.return_value = mock_user_settings

    result = await moderation_service.ban_subscriber(telegram_id, mock_translator)

    assert result.success is True
    assert "User {telegram_id} was banned." in result.message_key
    mock_uow.bans.add_ban.assert_called_once_with(
        telegram_id=telegram_id,
        teamtalk_username="test_tt_user",
        reason="Banned by admin",
    )
    mock_subscription_service.delete_profile.assert_not_called()


@pytest.mark.asyncio
async def test_unban_subscriber_success(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    mock_ban_entry_tg = MagicMock(telegram_id=telegram_id, teamtalk_username=None)
    mock_ban_entry_tt = MagicMock(telegram_id=None, teamtalk_username="test_tt_user")
    mock_uow.bans.get_by_telegram_id.return_value = [
        mock_ban_entry_tg,
        mock_ban_entry_tt,
    ]

    result = await moderation_service.unban_subscriber(telegram_id, mock_translator)

    assert result.success is True
    assert "User has been successfully unbanned." in result.message_key
    mock_uow.bans.remove_by_telegram_id.assert_called_once_with(telegram_id)
    mock_uow.bans.remove_by_teamtalk_username.assert_called_once_with("test_tt_user")


@pytest.mark.asyncio
async def test_toggle_mute_status_mute_new_user(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    tt_username = "new_tt_user"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")
    result = await moderation_service.toggle_mute_status(
        user_settings, tt_username, mock_translator
    )

    assert result.success is True
    assert "User {username} has been successfully muted." in result.message_key
    assert len(user_settings.muted_users_list) == 1
    assert user_settings.muted_users_list[0].muted_teamtalk_username == tt_username
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_called_once_with(user_settings)


@pytest.mark.asyncio
async def test_toggle_mute_status_unmute_existing_user(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    tt_username = "existing_tt_user"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")
    mock_muted_user = MagicMock(muted_teamtalk_username=tt_username)
    user_settings.muted_users_list = [mock_muted_user]

    result = await moderation_service.toggle_mute_status(
        user_settings, tt_username, mock_translator
    )

    assert result.success is True
    assert "User {username} has been successfully unmuted." in result.message_key
    assert len(user_settings.muted_users_list) == 0
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_called_once_with(user_settings)


@pytest.mark.asyncio
async def test_get_target_username_for_toggle_all_accounts(
    moderation_service: ModerationService,
    mock_command_bus: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    callback_data = MagicMock(
        list_type=UserListAction.LIST_ALL_ACCOUNTS, current_page=0, user_idx=0
    )
    user_settings = MagicMock()
    mock_command_bus.execute.return_value = MagicMock(
        success=True, accounts=[MagicMock(username="test_user")]
    )

    username = await moderation_service.get_target_username_for_toggle(
        callback_data, user_settings, mock_command_bus, mock_translator
    )

    assert username == "test_user"
    mock_command_bus.execute.assert_called_once()


@pytest.mark.asyncio
async def test_toggle_mute_from_callback_success(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_command_bus: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    tt_username = "test_user"
    callback_data = MagicMock(
        list_type=UserListAction.LIST_ALL_ACCOUNTS, current_page=0, user_idx=0
    )
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")
    user_settings.muted_users_list = []

    mock_uow.users.get_by_id.return_value = user_settings
    mock_command_bus.execute.return_value = MagicMock(
        success=True, accounts=[MagicMock(username=tt_username)]
    )

    result = await moderation_service.toggle_mute_from_callback(
        callback_data, telegram_id, mock_command_bus, mock_translator
    )

    assert result.success is True
    assert "User {username} has been successfully muted." in result.message_key
    assert len(user_settings.muted_users_list) == 1
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
