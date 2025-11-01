"""Tests for the notification service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.core.enums import NotificationType
from bot.database.models import UserSettings
from bot.database.types import MuteListMode
from bot.database.uow import SqlModelUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.notification_service import (
    NotificationRecipientService,
    is_linked_user_online,
    is_muted,
    is_user_subject_to_noon_check,
    should_send_silently,
)


@pytest.mark.parametrize(
    ("user_settings", "expected"),
    [
        (UserSettings(not_on_online_enabled=True, not_on_online_confirmed=True), True),
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
    user_settings: UserSettings | None, *, expected: bool
) -> None:
    """Test the is_user_subject_to_noon_check function."""
    assert is_user_subject_to_noon_check(user_settings) == expected


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
    username: str, mode: MuteListMode, muted_set: set[str], *, expected: bool
) -> None:
    """Test the is_muted function."""
    assert is_muted(username, mode, muted_set) == expected


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock(spec=CacheService)


@pytest.fixture
def mock_online_users() -> dict:
    user1 = MagicMock()
    user1.username = "test_user"
    return {1: user1}


def test_is_linked_user_online(mock_cache: MagicMock, mock_online_users: dict) -> None:
    mock_cache.get_user_settings.return_value = UserSettings(
        teamtalk_username="test_user"
    )
    assert is_linked_user_online(123, mock_cache, mock_online_users) is True

    mock_cache.get_user_settings.return_value = UserSettings(
        teamtalk_username="another_user"
    )
    assert is_linked_user_online(123, mock_cache, mock_online_users) is False


def test_should_send_silently(mock_cache: MagicMock, mock_online_users: dict) -> None:
    """Test the should_send_silently function."""

    # NOON enabled and user online
    mock_cache.get_user_settings.return_value = UserSettings(
        not_on_online_enabled=True,
        not_on_online_confirmed=True,
        teamtalk_username="test_user",
    )
    assert should_send_silently(123, mock_cache, mock_online_users) is True

    # NOON disabled
    mock_cache.get_user_settings.return_value = UserSettings(
        not_on_online_enabled=False,
        not_on_online_confirmed=True,
        teamtalk_username="test_user",
    )
    assert should_send_silently(123, mock_cache, mock_online_users) is False

    # User not online
    mock_cache.get_user_settings.return_value = UserSettings(
        not_on_online_enabled=True,
        not_on_online_confirmed=True,
        teamtalk_username="another_user",
    )
    assert should_send_silently(123, mock_cache, mock_online_users) is False


@pytest.mark.asyncio
async def test_find_recipients(mock_cache: MagicMock) -> None:
    """Test the find_recipients method of NotificationRecipientService."""
    # Mock the session and UoW
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(1, "en")]
    mock_session.execute.return_value = mock_result

    # Mock the session factory to return our mock session
    mock_session_factory = MagicMock(return_value=mock_session)

    # Temporarily patch SqlModelUnitOfWork for this test
    original_aenter = SqlModelUnitOfWork.__aenter__
    uow_mock = AsyncMock()
    uow_mock.session = mock_session
    SqlModelUnitOfWork.__aenter__ = AsyncMock(return_value=uow_mock)

    service = NotificationRecipientService(mock_session_factory, mock_cache)
    mock_cache.get_all_subscriber_ids.return_value = {1, 2, 3}

    recipients = await service.find_recipients("test_user", NotificationType.JOIN)

    assert recipients == [(1, "en")]
    mock_session.execute.assert_called_once()

    # Restore original __aenter__
    SqlModelUnitOfWork.__aenter__ = original_aenter
