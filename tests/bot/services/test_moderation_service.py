from gettext import NullTranslations
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import (
    DatabaseSettings,
    GeneralSettings,
    Settings,
    TeamTalkSettings,
    TelegramSettings,
)  # Added imports
from bot.core.enums import UserListAction
from bot.database.models import UserSettings
from bot.database.uow import IUnitOfWork  # Import IUnitOfWork
from bot.services.moderation_service import ModerationService
from bot.services.teamtalk_service import TeamTalkService
from bot.teamtalk_bot.connection import TeamTalkConnection


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
def mock_tt_connection() -> AsyncMock:
    conn = AsyncMock(spec=TeamTalkConnection)
    conn.ttstr = lambda x: x.decode() if isinstance(x, bytes) else x
    return conn


@pytest.fixture
def mock_teamtalk_service() -> AsyncMock:
    return AsyncMock(spec=TeamTalkService)


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
def mock_settings() -> Settings:
    """Mock Settings object for testing."""
    return Settings(
        general=GeneralSettings(admin_username="test_admin"),
        database=DatabaseSettings(db_file="test.db"),  # Provided valid instance
        telegram=TelegramSettings(
            event_token="test_event_token",
            message_token="test_message_token",
            admin_chat_id=12345,
        ),  # Provided valid instance
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
def moderation_service(
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
    mock_tt_connection: AsyncMock,
    mock_teamtalk_service: AsyncMock,
) -> ModerationService:
    return ModerationService(
        uow=mock_uow,
        subscription_service=mock_subscription_service,
        cache=mock_cache,
        settings=mock_settings,
        tt_connection=mock_tt_connection,
        teamtalk_service=mock_teamtalk_service,
    )


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

    result = await moderation_service.ban_subscriber(
        mock_uow, telegram_id, mock_translator
    )

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

    result = await moderation_service.unban_subscriber(
        mock_uow, telegram_id, mock_translator
    )

    assert result.success is True
    assert "User has been successfully unbanned." in result.message_key
    mock_uow.bans.remove_by_telegram_id.assert_called_once_with(telegram_id)
    mock_uow.bans.remove_by_teamtalk_username.assert_called_once_with("test_tt_user")


@pytest.mark.asyncio
async def test_kick_user_from_server_success(
    moderation_service: ModerationService,
    mock_tt_connection: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    user_id = 1
    admin_telegram_id = 123
    mock_user_to_act_on = MagicMock(
        id=user_id, nickname="KickUser", username=b"kickuser"
    )
    mock_tt_connection.instance = MagicMock()
    mock_tt_connection.instance.get_user.return_value = mock_user_to_act_on
    mock_tt_connection.instance.server = MagicMock()
    mock_tt_connection.instance.server.get_properties.return_value.server_name = (
        "TestServer"
    )
    mock_tt_connection.is_ready = True
    mock_tt_connection.ttstr.side_effect = (
        lambda x: x.decode() if isinstance(x, bytes) else x
    )

    result = await moderation_service.kick_user_from_server(
        user_id=user_id, admin_telegram_id=admin_telegram_id, translator=mock_translator
    )

    assert result.success is True
    assert "User KickUser kicked from server TestServer." in result.message_key
    mock_tt_connection.instance.get_user.assert_called_once_with(user_id)
    mock_user_to_act_on.kick.assert_called_once_with(from_server=True)


@pytest.mark.asyncio
async def test_ban_user_from_server_success(
    moderation_service: ModerationService,
    mock_tt_connection: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    user_id = 1
    admin_telegram_id = 123
    mock_user_to_act_on = MagicMock(id=user_id, nickname="BanUser", username=b"banuser")
    mock_tt_connection.instance = MagicMock()
    mock_tt_connection.instance.get_user.return_value = mock_user_to_act_on
    mock_tt_connection.instance.server = MagicMock()
    mock_tt_connection.instance.server.get_properties.return_value.server_name = (
        "TestServer"
    )
    mock_tt_connection.is_ready = True
    mock_tt_connection.ttstr.side_effect = (
        lambda x: x.decode() if isinstance(x, bytes) else x
    )

    result = await moderation_service.ban_user_from_server(
        user_id=user_id, admin_telegram_id=admin_telegram_id, translator=mock_translator
    )

    assert result.success is True
    assert (
        "User BanUser banned and kicked from server TestServer." in result.message_key
    )
    mock_tt_connection.instance.get_user.assert_called_once_with(user_id)
    mock_user_to_act_on.ban.assert_called_once_with(from_server=True)
    mock_user_to_act_on.kick.assert_called_once_with(from_server=True)


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
        mock_uow, user_settings, tt_username, mock_translator
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
        mock_uow, user_settings, tt_username, mock_translator
    )

    assert result.success is True
    assert "User {username} has been successfully unmuted." in result.message_key
    assert len(user_settings.muted_users_list) == 0
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_called_once_with(user_settings)


@pytest.mark.asyncio
async def test_get_target_username_for_toggle_all_accounts(
    moderation_service: ModerationService,
    mock_teamtalk_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    user_settings = MagicMock()
    mock_teamtalk_service.fetch_all_accounts.return_value = (
        [MagicMock(username="test_user")],
        None,
    )

    username = await moderation_service.get_target_username_for_toggle(
        list_type=UserListAction.LIST_ALL_ACCOUNTS,
        page=0,
        index_on_page=0,
        user_settings=user_settings,
        translator=mock_translator,
    )

    assert username == "test_user"
    mock_teamtalk_service.fetch_all_accounts.assert_called_once()


@pytest.mark.asyncio
async def test_toggle_mute_from_paginated_list_success(
    moderation_service: ModerationService,
    mock_uow: AsyncMock,
    mock_teamtalk_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    tt_username = "test_user"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")
    user_settings.muted_users_list = []

    mock_uow.users.get_by_id.return_value = user_settings
    mock_teamtalk_service.fetch_all_accounts.return_value = (
        [MagicMock(username=tt_username)],
        None,
    )

    result = await moderation_service.toggle_mute_from_paginated_list(
        mock_uow,
        telegram_id=telegram_id,
        list_type=UserListAction.LIST_ALL_ACCOUNTS,
        page=0,
        index_on_page=0,
        translator=mock_translator,
    )

    assert result.success is True
    assert "User {username} has been successfully muted." in result.message_key
    assert len(user_settings.muted_users_list) == 1
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
