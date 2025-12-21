"""Tests for the notification service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.enums import NotificationType
from bot.database.models import UserSettings
from bot.database.types import MuteListMode
from bot.services.cache_service import CacheService
from bot.services.notification_service import (
    NotificationRecipientService,
)
from bot.services.schemas import RecipientDTO


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock(spec=CacheService)


@pytest.fixture
def service(mock_cache: MagicMock) -> NotificationRecipientService:
    return NotificationRecipientService(cache=mock_cache)


@pytest.fixture
def mock_online_users() -> dict:
    user1 = MagicMock()
    user1.username = "test_user"
    return {1: user1}


@pytest.mark.parametrize(
    ("user_settings", "expected"),
    [
        (
            UserSettings(not_on_online_enabled=True, not_on_online_confirmed=True),
            True,
        ),
        (
            UserSettings(not_on_online_enabled=False, not_on_online_confirmed=True),
            False,
        ),
        (
            UserSettings(not_on_online_enabled=True, not_on_online_confirmed=False),
            False,
        ),
        (None, False),
    ],
)
def test_is_user_subject_to_noon_check(
    service: NotificationRecipientService,
    user_settings: UserSettings | None,
    *,
    expected: bool,
) -> None:
    """Test the is_user_subject_to_noon_check method."""
    assert service.is_user_subject_to_noon_check(user_settings) == expected


@pytest.mark.parametrize(
    ("username", "mode", "muted_set", "expected"),
    [
        ("user1", MuteListMode.blacklist, {"user1", "user2"}, True),
        ("user3", MuteListMode.blacklist, {"user1", "user2"}, False),
        ("user1", MuteListMode.whitelist, {"user1", "user2"}, False),
        ("user3", MuteListMode.whitelist, {"user1", "user2"}, True),
    ],
)
def test_is_muted(
    service: NotificationRecipientService,
    username: str,
    mode: MuteListMode,
    muted_set: set[str],
    *,
    expected: bool,
) -> None:
    """Test the is_muted static method."""
    assert service.is_muted(username, mode, muted_set) == expected


def test_is_linked_user_online(
    service: NotificationRecipientService,
    mock_cache: MagicMock,
    mock_online_users: dict,
) -> None:
    """Test the is_linked_user_online method."""
    mock_cache.get_user_settings.return_value = UserSettings(
        teamtalk_username="test_user"
    )
    assert service.is_linked_user_online(123, mock_online_users) is True

    mock_cache.get_user_settings.return_value = UserSettings(
        teamtalk_username="another_user"
    )
    assert service.is_linked_user_online(123, mock_online_users) is False


def test_should_send_silently(
    service: NotificationRecipientService,
    mock_cache: MagicMock,
    mock_online_users: dict,
) -> None:
    """Test the should_send_silently method."""
    # NOON enabled and user online
    mock_cache.get_user_settings.return_value = UserSettings(
        not_on_online_enabled=True,
        not_on_online_confirmed=True,
        teamtalk_username="test_user",
    )
    assert service.should_send_silently(123, mock_online_users) is True

    # NOON disabled
    mock_cache.get_user_settings.return_value = UserSettings(
        not_on_online_enabled=False,
        not_on_online_confirmed=True,
        teamtalk_username="test_user",
    )
    assert service.should_send_silently(123, mock_online_users) is False

    # User not online
    mock_cache.get_user_settings.return_value = UserSettings(
        not_on_online_enabled=True,
        not_on_online_confirmed=True,
        teamtalk_username="another_user",
    )
    assert service.should_send_silently(123, mock_online_users) is False


@pytest.mark.asyncio
async def test_find_recipients(
    service: NotificationRecipientService, mock_cache: MagicMock
) -> None:
    """Test the find_recipients method of NotificationRecipientService."""
    # Mock the UoW and repository method
    uow_mock = AsyncMock()
    uow_mock.users.get_notification_recipients = AsyncMock(return_value=[(1, "en")])

    subscriber_ids = {1, 2, 3}
    mock_cache.get_all_subscriber_ids.return_value = subscriber_ids

    recipients = await service.find_recipients(
        uow_mock, "test_user", NotificationType.JOIN
    )

    assert recipients == [RecipientDTO(telegram_id=1, language_code="en")]
    uow_mock.users.get_notification_recipients.assert_called_once_with(
        list(subscriber_ids), "test_user", NotificationType.JOIN
    )
