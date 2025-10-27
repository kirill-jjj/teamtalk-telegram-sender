from gettext import NullTranslations
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.database.models import (
    SubscribedUser,
    UserSettings,
)  # Import Admin for completeness if needed
from bot.database.uow import IUnitOfWork
from bot.services.subscription_service import SubscriptionService


@pytest.fixture
def mock_uow() -> AsyncMock:
    uow = AsyncMock(spec=IUnitOfWork)
    uow.subscribers = AsyncMock()
    uow.users = AsyncMock()
    uow.bans = AsyncMock()
    return uow


@pytest.fixture
def mock_cache() -> MagicMock:
    cache = MagicMock()
    cache.add_subscriber = MagicMock()
    cache.update_user_settings = MagicMock()
    cache.remove_user_profile = MagicMock()
    return cache


@pytest.fixture
def mock_translator() -> MagicMock:
    translator = MagicMock(spec=NullTranslations)
    translator.gettext.side_effect = lambda x: x
    return translator


@pytest.fixture
def subscription_service(
    mock_uow: AsyncMock, mock_cache: MagicMock
) -> SubscriptionService:
    return SubscriptionService(mock_uow, mock_cache)


@pytest.mark.asyncio
async def test_create_subscription_new_user(
    subscription_service: SubscriptionService,
    mock_uow: AsyncMock,
) -> None:
    user_settings = UserSettings(telegram_id=123, language_code="en")
    tt_username = "test_tt_user"

    result = await subscription_service.create_subscription(
        mock_uow, user_settings, tt_username
    )

    assert result is True


@pytest.mark.asyncio
async def test_create_subscription_existing_user(
    subscription_service: SubscriptionService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
) -> None:
    user_settings = UserSettings(
        telegram_id=123,
        language_code="en",
        teamtalk_username="old_tt_user",
        not_on_online_confirmed=False,
    )
    tt_username = "new_tt_user"

    mock_uow.subscribers.get_by_id.return_value = SubscribedUser(
        telegram_id=user_settings.telegram_id
    )

    result = await subscription_service.create_subscription(
        mock_uow, user_settings, tt_username
    )

    assert result is True
    mock_uow.subscribers.get_by_id.assert_called_once_with(user_settings.telegram_id)
    mock_uow.subscribers.add.assert_not_called()  # Should not add again
    mock_cache.add_subscriber.assert_not_called()  # Should not add again
    assert user_settings.teamtalk_username == tt_username
    assert user_settings.not_on_online_confirmed is True
    mock_uow.users.save.assert_called_once_with(user_settings)


@pytest.mark.asyncio
async def test_delete_profile_full_user(
    subscription_service: SubscriptionService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    mock_user_settings = UserSettings(telegram_id=telegram_id, language_code="en")

    mock_uow.users.get_by_id.return_value = mock_user_settings
    mock_subscribed_user = SubscribedUser(telegram_id=telegram_id)
    mock_uow.subscribers.get_by_id.return_value = mock_subscribed_user

    result = await subscription_service.delete_profile(
        mock_uow, telegram_id, mock_translator
    )

    assert result.success is True
    assert "Subscriber {telegram_id} deleted successfully." in result.message_key
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.delete.assert_called_once_with(mock_user_settings)
    mock_uow.subscribers.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.subscribers.delete.assert_called_once_with(mock_subscribed_user)
    mock_cache.remove_user_profile.assert_called_once_with(telegram_id)


@pytest.mark.asyncio
async def test_delete_profile_only_settings(
    subscription_service: SubscriptionService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    mock_user_settings = UserSettings(telegram_id=telegram_id, language_code="en")

    mock_uow.users.get_by_id.return_value = mock_user_settings
    mock_uow.subscribers.get_by_id.return_value = None  # No subscribed user
    result = await subscription_service.delete_profile(
        mock_uow, telegram_id, mock_translator
    )

    assert result.success is True
    assert "Subscriber {telegram_id} deleted successfully." in result.message_key
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.delete.assert_called_once_with(mock_user_settings)
    mock_uow.subscribers.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.subscribers.delete.assert_not_called()
    mock_cache.remove_user_profile.assert_called_once_with(telegram_id)


@pytest.mark.asyncio
async def test_link_tt_account_new_link(
    subscription_service: SubscriptionService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    user_settings = UserSettings(
        telegram_id=telegram_id, language_code="en", teamtalk_username=None
    )
    tt_username = "new_tt_user"

    mock_uow.bans.is_teamtalk_username_banned.return_value = False

    result = await subscription_service.link_tt_account(
        mock_uow, user_settings, tt_username, mock_translator
    )

    assert result.success is True
    assert (
        "Successfully linked TeamTalk account: {new_tt_username}." in result.message_key
    )
    assert result.message_args["new_tt_username"] == tt_username
    assert user_settings.teamtalk_username == tt_username
    assert user_settings.not_on_online_confirmed is True
    mock_uow.bans.is_teamtalk_username_banned.assert_called_once_with(tt_username)
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_called_once_with(user_settings)


@pytest.mark.asyncio
async def test_link_tt_account_relink(
    subscription_service: SubscriptionService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    user_settings = UserSettings(
        telegram_id=telegram_id, language_code="en", teamtalk_username="old_tt_user"
    )
    tt_username = "new_tt_user"

    mock_uow.bans.is_teamtalk_username_banned.return_value = False

    result = await subscription_service.link_tt_account(
        mock_uow, user_settings, tt_username, mock_translator
    )

    assert result.success is True
    assert (
        "Successfully relinked TeamTalk account to {new_tt_username} (was "
        "{original_tt_username})." in result.message_key
    )
    assert result.message_args["new_tt_username"] == tt_username
    assert result.message_args["original_tt_username"] == "old_tt_user"
    assert user_settings.teamtalk_username == tt_username
    assert user_settings.not_on_online_confirmed is True
    mock_uow.bans.is_teamtalk_username_banned.assert_called_once_with(tt_username)
    mock_uow.users.save.assert_called_once_with(user_settings)
    mock_cache.update_user_settings.assert_called_once_with(user_settings)


@pytest.mark.asyncio
async def test_link_tt_account_banned_username(
    subscription_service: SubscriptionService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    user_settings = UserSettings(
        telegram_id=telegram_id, language_code="en", teamtalk_username=None
    )
    tt_username = "banned_tt_user"

    mock_uow.bans.is_teamtalk_username_banned.return_value = True

    result = await subscription_service.link_tt_account(
        mock_uow, user_settings, tt_username, mock_translator
    )

    assert result.success is False
    assert (
        "Cannot link TeamTalk account: username {tt_username} is banned."
        in result.message_key
    )
    assert result.message_args["tt_username"] == tt_username
    assert user_settings.teamtalk_username is None  # Should not be updated
    assert user_settings.not_on_online_confirmed is False  # Should not be updated
    mock_uow.bans.is_teamtalk_username_banned.assert_called_once_with(tt_username)
    mock_uow.users.save.assert_not_called()
    mock_cache.update_user_settings.assert_not_called()


@pytest.mark.asyncio
async def test_delete_profile_only_subscribed(
    subscription_service: SubscriptionService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    mock_subscribed_user = SubscribedUser(telegram_id=telegram_id)

    mock_uow.users.get_by_id.return_value = None  # No user settings
    mock_uow.subscribers.get_by_id.return_value = mock_subscribed_user

    result = await subscription_service.delete_profile(
        mock_uow, telegram_id, mock_translator
    )

    assert result.success is True
    assert "Subscriber {telegram_id} deleted successfully." in result.message_key
    mock_cache.remove_user_profile.assert_called_once_with(telegram_id)


@pytest.mark.asyncio
async def test_delete_profile_non_existent_user(
    subscription_service: SubscriptionService,
    mock_uow: AsyncMock,
    mock_cache: MagicMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123

    mock_uow.users.get_by_id.return_value = None
    mock_uow.subscribers.get_by_id.return_value = None

    result = await subscription_service.delete_profile(
        mock_uow, telegram_id, mock_translator
    )

    assert result.success is True
    assert "Subscriber {telegram_id} deleted successfully." in result.message_key
    mock_uow.users.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.users.delete.assert_not_called()
    mock_uow.subscribers.get_by_id.assert_called_once_with(telegram_id)
    mock_uow.subscribers.delete.assert_not_called()
    mock_cache.remove_user_profile.assert_called_once_with(telegram_id)
