from datetime import UTC, datetime, timedelta
from gettext import NullTranslations
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.enums import DeeplinkAction
from bot.database.models import Deeplink as DeeplinkModel
from bot.database.models import UserSettings
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.subscription_service import SubscriptionService


@pytest.fixture
def mock_uow() -> AsyncMock:
    uow = AsyncMock(spec=IUnitOfWork)
    uow.deeplinks = AsyncMock()
    uow.users = AsyncMock()
    uow.bans = AsyncMock()
    uow.admins = AsyncMock()
    return uow


@pytest.fixture
def mock_subscription_service() -> AsyncMock:
    return AsyncMock(spec=SubscriptionService)


@pytest.fixture
def mock_cache() -> MagicMock:
    cache = MagicMock(spec=CacheService)
    cache.get_bot_username.return_value = "test_bot"
    cache.add_admin = MagicMock()
    return cache


@pytest.fixture
def mock_translator() -> MagicMock:
    translator = MagicMock(spec=NullTranslations)
    translator.gettext.side_effect = lambda x: x
    translator.info.return_value = {"language": "en"}
    return translator


@pytest.fixture
def deeplink_service(
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_cache: MagicMock,
) -> DeeplinkService:
    return DeeplinkService(mock_uow, mock_subscription_service, mock_cache)


@pytest.mark.asyncio
async def test_create_deeplink_success(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
) -> None:
    """Tests that the create_deeplink static method correctly calls the UoW."""
    mock_uow.deeplinks.create.return_value = DeeplinkModel(
        token="test_token",
        action=DeeplinkAction.SUBSCRIBE,
        payload="test_payload",
        expiry_time=datetime.now(UTC) + timedelta(minutes=5),
    )

    result = await deeplink_service.create_deeplink(
        mock_uow, DeeplinkAction.SUBSCRIBE, 300, "test_payload"
    )

    mock_uow.deeplinks.create.assert_called_once_with(
        DeeplinkAction.SUBSCRIBE, 300, payload="test_payload"
    )
    assert isinstance(result, DeeplinkModel)
    assert result.action == DeeplinkAction.SUBSCRIBE
    assert result.payload == "test_payload"


@pytest.mark.asyncio
async def test_execute_subscribe_success(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    payload = "test_tt_user"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")

    mock_uow.reset_mock()
    mock_uow.bans.is_telegram_id_banned.return_value = False
    mock_uow.bans.is_teamtalk_username_banned.return_value = False
    mock_subscription_service.create_subscription.return_value = True
    mock_uow.admins.get_by_id.return_value = None  # Ensure user is not an admin

    result = await deeplink_service._execute_subscribe(
        mock_uow, telegram_id, mock_translator, payload, user_settings
    )

    mock_uow.bans.is_telegram_id_banned.assert_called_once_with(telegram_id)
    mock_uow.bans.is_teamtalk_username_banned.assert_called_once_with(payload)
    mock_subscription_service.create_subscription.assert_called_once_with(
        mock_uow, user_settings, payload
    )
    mock_cache.add_admin.assert_not_called()
    assert "You have successfully subscribed to notifications." in result


@pytest.mark.asyncio
async def test_execute_subscribe_telegram_id_banned(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    payload = "test_tt_user"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")
    mock_uow.bans.is_telegram_id_banned.return_value = True
    result = await deeplink_service._execute_subscribe(
        mock_uow, telegram_id, mock_translator, payload, user_settings
    )

    mock_uow.bans.is_telegram_id_banned.assert_called_once_with(telegram_id)
    mock_uow.bans.is_teamtalk_username_banned.assert_not_called()
    mock_subscription_service.create_subscription.assert_not_called()
    assert "Your Telegram account is banned from using this service." in result


@pytest.mark.asyncio
async def test_execute_subscribe_missing_payload(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    payload = None
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")
    mock_uow.bans.is_telegram_id_banned.return_value = False

    result = await deeplink_service._execute_subscribe(
        mock_uow, telegram_id, mock_translator, payload, user_settings
    )

    mock_uow.bans.is_telegram_id_banned.assert_called_once_with(telegram_id)
    mock_uow.bans.is_teamtalk_username_banned.assert_not_called()
    mock_subscription_service.create_subscription.assert_not_called()
    assert "Error: Missing required information for subscription." in result


@pytest.mark.asyncio
async def test_execute_subscribe_teamtalk_username_banned(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    payload = "banned_tt_user"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")

    mock_uow.bans.is_telegram_id_banned.return_value = False
    mock_uow.bans.is_teamtalk_username_banned.return_value = True

    result = await deeplink_service._execute_subscribe(
        mock_uow, telegram_id, mock_translator, payload, user_settings
    )

    mock_uow.bans.is_telegram_id_banned.assert_called_once_with(telegram_id)
    mock_uow.bans.is_teamtalk_username_banned.assert_called_once_with(payload)
    mock_subscription_service.create_subscription.assert_not_called()
    assert f"The TeamTalk username '{payload}' is banned." in result


@pytest.mark.asyncio
async def test_execute_subscribe_create_subscription_fails(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    payload = "test_tt_user"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")

    mock_uow.bans.is_telegram_id_banned.return_value = False
    mock_uow.bans.is_teamtalk_username_banned.return_value = False
    mock_subscription_service.create_subscription.return_value = False
    result = await deeplink_service._execute_subscribe(
        mock_uow, telegram_id, mock_translator, payload, user_settings
    )

    mock_subscription_service.create_subscription.assert_called_once_with(
        mock_uow, user_settings, payload
    )
    assert "An error occurred. Please try again later." in result


@pytest.mark.asyncio
async def test_execute_subscribe_user_is_admin(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
    mock_cache: MagicMock,
) -> None:
    telegram_id = 123
    payload = "test_tt_user"
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")

    mock_uow.bans.is_telegram_id_banned.return_value = False
    mock_uow.bans.is_teamtalk_username_banned.return_value = False
    mock_subscription_service.create_subscription.return_value = True
    mock_uow.admins.get_by_id.return_value = MagicMock()  # User is an admin

    result = await deeplink_service._execute_subscribe(
        mock_uow, telegram_id, mock_translator, payload, user_settings
    )

    mock_uow.admins.get_by_id.assert_called_once_with(telegram_id)
    mock_cache.add_admin.assert_called_once_with(telegram_id)
    assert "You have successfully subscribed to notifications." in result


@pytest.mark.asyncio
async def test_execute_unsubscribe_success(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    mock_subscription_service.delete_profile.return_value = True
    result = await deeplink_service._execute_unsubscribe(
        mock_uow, telegram_id, mock_translator
    )

    mock_subscription_service.delete_profile.assert_called_once_with(
        mock_uow, telegram_id, mock_translator
    )
    assert "You have successfully unsubscribed from notifications." in result


@pytest.mark.asyncio
async def test_execute_unsubscribe_not_subscribed(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    telegram_id = 123
    mock_subscription_service.delete_profile.return_value = False
    result = await deeplink_service._execute_unsubscribe(
        mock_uow, telegram_id, mock_translator
    )

    mock_subscription_service.delete_profile.assert_called_once_with(
        mock_uow, telegram_id, mock_translator
    )
    assert "You were not subscribed to notifications." in result


@pytest.mark.asyncio
async def test_execute_deeplink_subscribe_action(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    deeplink = DeeplinkModel(
        action=DeeplinkAction.SUBSCRIBE,
        token="abc",
        payload="test_tt_user",
        expiry_time=datetime.now(UTC) + timedelta(minutes=5),
    )
    user_settings = UserSettings(telegram_id=123, language_code="en")
    mock_uow.bans.is_telegram_id_banned.return_value = False
    mock_uow.bans.is_teamtalk_username_banned.return_value = False
    mock_subscription_service.create_subscription.return_value = True
    result = await deeplink_service.execute_deeplink(
        mock_uow, deeplink, user_settings, mock_translator
    )

    assert "You have successfully subscribed to notifications." in result


@pytest.mark.asyncio
async def test_execute_deeplink_unsubscribe_action(
    deeplink_service: DeeplinkService,
    mock_translator: MagicMock,
) -> None:
    deeplink_token_value = "abc"
    deeplink = DeeplinkModel(
        action=DeeplinkAction.UNSUBSCRIBE,
        token=deeplink_token_value,
        expiry_time=datetime.now(UTC) + timedelta(minutes=5),
    )
    telegram_id = 123
    user_settings = UserSettings(telegram_id=telegram_id, language_code="en")
    result = await deeplink_service.execute_deeplink(
        mock_uow, deeplink, user_settings, mock_translator
    )

    assert "You have successfully unsubscribed from notifications." in result


@pytest.mark.asyncio
async def test_execute_telegram_deeplink_success(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_subscription_service: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    token = "valid_token"
    telegram_id = 123
    default_lang = "en"
    user_settings = UserSettings(telegram_id=telegram_id, language_code=default_lang)
    deeplink = DeeplinkModel(
        token=token,
        action=DeeplinkAction.SUBSCRIBE,
        payload="test_tt_user",
        expected_telegram_id=telegram_id,
        expiry_time=datetime.now(UTC) + timedelta(minutes=5),
    )

    mock_uow.users.get_or_create.return_value = user_settings
    mock_uow.deeplinks.resolve_token.return_value = deeplink
    mock_uow.bans.is_telegram_id_banned.return_value = False
    mock_uow.bans.is_teamtalk_username_banned.return_value = False
    mock_subscription_service.create_subscription.return_value = True
    mock_uow.admins.get_by_id.return_value = None

    reply_text, success = await deeplink_service.execute_telegram_deeplink(
        mock_uow, token, mock_translator, telegram_id, default_lang
    )

    mock_uow.users.get_or_create.assert_called_once_with(
        telegram_id, defaults={"language_code": default_lang}
    )
    mock_uow.deeplinks.resolve_token.assert_called_once_with(token)
    mock_uow.deeplinks.delete.assert_called_once_with(deeplink)
    assert "You have successfully subscribed to notifications." in reply_text
    assert success is True


@pytest.mark.asyncio
async def test_execute_telegram_deeplink_invalid_or_expired_deeplink(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    token = "invalid_token"
    telegram_id = 123
    default_lang = "en"
    user_settings = UserSettings(telegram_id=telegram_id, language_code=default_lang)

    mock_uow.users.get_or_create.return_value = user_settings
    mock_uow.deeplinks.resolve_token.return_value = None

    reply_text, success = await deeplink_service.execute_telegram_deeplink(
        mock_uow, token, mock_translator, telegram_id, default_lang
    )

    mock_uow.users.get_or_create.assert_called_once_with(
        telegram_id, defaults={"language_code": default_lang}
    )
    mock_uow.deeplinks.resolve_token.assert_called_once_with(token)
    mock_uow.deeplinks.delete.assert_not_called()
    assert "Invalid or expired deeplink." in reply_text
    assert success is False


@pytest.mark.asyncio
async def test_execute_telegram_deeplink_intended_for_different_user(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
    mock_translator: MagicMock,
) -> None:
    token = "valid_token"
    telegram_id = 123
    default_lang = "en"
    user_settings = UserSettings(telegram_id=telegram_id, language_code=default_lang)
    deeplink = DeeplinkModel(
        token=token,
        action=DeeplinkAction.SUBSCRIBE,
        payload="test_tt_user",
        expected_telegram_id=456,  # Different user
        expiry_time=datetime.now(UTC) + timedelta(minutes=5),
    )

    mock_uow.users.get_or_create.return_value = user_settings
    mock_uow.deeplinks.resolve_token.return_value = deeplink

    reply_text, success = await deeplink_service.execute_telegram_deeplink(
        mock_uow, token, mock_translator, telegram_id, default_lang
    )

    mock_uow.users.get_or_create.assert_called_once_with(
        telegram_id, defaults={"language_code": default_lang}
    )
    mock_uow.deeplinks.resolve_token.assert_called_once_with(token)
    mock_uow.deeplinks.delete.assert_not_called()
    assert (
        "This confirmation link was intended for a different Telegram account."
        in reply_text
    )
    assert success is False


@pytest.mark.asyncio
async def test_cleanup_expired_deeplinks(
    deeplink_service: DeeplinkService,
    mock_uow: AsyncMock,
) -> None:
    """Test the cleanup_expired_deeplinks method."""
    # Arrange
    expected_deleted_count = 5
    mock_uow.deeplinks.delete_expired.return_value = expected_deleted_count

    # Act
    deleted_count = await deeplink_service.cleanup_expired_deeplinks()

    # Assert
    assert deleted_count == expected_deleted_count
    mock_uow.deeplinks.delete_expired.assert_called_once()
