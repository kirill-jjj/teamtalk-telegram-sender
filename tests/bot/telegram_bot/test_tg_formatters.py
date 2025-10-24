"""Tests for Telegram bot formatters."""

from gettext import NullTranslations
from unittest.mock import MagicMock

from aiogram.types import Chat
import pytest

from bot.core.enums import AdminCommand
from bot.models import MuteListMode, NotificationSetting
from bot.services.schemas import SettingsViewDTO
from bot.telegram_bot.formatters import (
    format_help_text,
    format_manage_muted_menu_text,
    format_moderation_prompt,
    format_mute_toast,
    format_paginated_list_text,
    format_subscriber_details,
    format_telegram_user_display_name,
    format_who_report_to_html,
)
from bot.telegram_bot.models import (
    WhoChannelGroup,
    WhoReport,
    WhoReportPayload,
    WhoUser,
)


@pytest.fixture
def mock_translator() -> MagicMock:
    translator = MagicMock(spec=NullTranslations)

    def gettext_side_effect(s: str) -> str:
        # A more flexible mock that can handle different format strings
        if "{username}" in s and "{action}" in s:
            return s.format(username="<test_user>", action="<action>")
        if "{server_host}" in s:
            return s.format(server_host="Test Server")
        if "{current_mode_description}" in s:
            return s.format(current_mode_description="Current mode is Blacklist.")
        return s

    translator.gettext.side_effect = gettext_side_effect
    translator.ngettext.side_effect = lambda s, p, n: s if n == 1 else p
    return translator


@pytest.mark.parametrize(
    ("username", "was_added", "mode", "expected_action"),
    [
        ("test_user", True, MuteListMode.blacklist, "added to blacklist"),
        ("test_user", False, MuteListMode.blacklist, "removed from blacklist"),
        ("test_user", True, MuteListMode.whitelist, "added to whitelist"),
        ("test_user", False, MuteListMode.whitelist, "removed from whitelist"),
    ],
)
def test_format_mute_toast(
    username: str,
    was_added: bool,
    mode: MuteListMode,
    expected_action: str,
    mock_translator: MagicMock,
) -> None:
    """Test the format_mute_toast function."""
    # Adjust the mock to return the specific action text
    mock_translator.gettext.side_effect = (
        lambda s: expected_action
        if s
        in {
            "added to blacklist",
            "removed from blacklist",
            "added to whitelist",
            "removed from whitelist",
        }
        else s.format(username=username, action=expected_action)
    )

    result = format_mute_toast(
        username_to_toggle=username,
        was_added_to_list=was_added,
        current_mode=mode,
        translator=mock_translator,
    )
    assert username in result
    assert expected_action in result


@pytest.mark.parametrize(
    ("chat_data", "expected_name"),
    [
        (
            {
                "id": 123,
                "type": "private",
                "first_name": "John",
                "last_name": "Doe",
                "username": "johndoe",
            },
            "John Doe (@johndoe)",
        ),
        (
            {"id": 123, "type": "private", "first_name": "John", "username": "johndoe"},
            "John (@johndoe)",
        ),
        ({"id": 123, "type": "private", "first_name": "John"}, "John"),
        ({"id": 123, "type": "private", "username": "johndoe"}, "@johndoe"),
        ({"id": 123, "type": "private"}, "123"),
        (None, "Unknown User"),
    ],
)
def test_format_telegram_user_display_name(
    chat_data: dict | None, expected_name: str
) -> None:
    """Test the format_telegram_user_display_name function."""
    chat = Chat(**chat_data) if chat_data else None
    result = format_telegram_user_display_name(chat)
    assert result == expected_name


def test_format_subscriber_details(mock_translator: MagicMock) -> None:
    """Test the format_subscriber_details function."""

    user_settings = SettingsViewDTO(
        telegram_id=123,
        language_code="en",
        notification_settings=NotificationSetting.ALL,
        mute_list_mode=MuteListMode.blacklist,
        not_on_online_enabled=True,
        not_on_online_confirmed=True,
        teamtalk_username="test_tt_user",
        muted_users_count=5,
    )
    display_name = "John Doe"

    # Adjust mock to handle specific keys
    key_map = {
        f"Subscriber: {display_name}": f"Subscriber: {display_name}",
        "Enabled": "Enabled",
        f"Linked TT Account: {user_settings.teamtalk_username}": (
            f"Linked TT Account: {user_settings.teamtalk_username}"
        ),
        f"Language: {user_settings.language_code}": (
            f"Language: {user_settings.language_code}"
        ),
        "NOON (Not on Online): {status}": "NOON (Not on Online): Enabled",
        "All (Join & Leave)": "All (Join & Leave)",
        "Notifications: {setting}": "Notifications: All (Join & Leave)",
        "Blacklist": "Blacklist",
        "Mute Mode: {mode}": "Mute Mode: Blacklist",
    }
    mock_translator.gettext.side_effect = lambda s: key_map.get(s, s)

    result = format_subscriber_details(user_settings, display_name, mock_translator)

    assert "Subscriber: John Doe" in result
    assert "Linked TT Account: test_tt_user" in result
    assert "Language: en" in result
    assert "NOON (Not on Online): Enabled" in result
    assert "Notifications: All (Join & Leave)" in result
    assert "Mute Mode: Blacklist" in result


def test_format_who_report_to_html(mock_translator: MagicMock) -> None:
    """Test the format_who_report_to_html function."""

    # Test with users
    payload = WhoReportPayload(
        server_name="Test Server",
        total_users=2,
        grouped_data=[
            WhoChannelGroup(
                channel_name="Channel 1", users=[WhoUser(nickname="User1")]
            ),
            WhoChannelGroup(
                channel_name="Channel 2", users=[WhoUser(nickname="User2")]
            ),
        ],
    )
    report = WhoReport(payload=payload)
    mock_translator.ngettext.return_value = (
        "There are {user_count} users on the server {server_host}:"
    )

    result = format_who_report_to_html(report, mock_translator)
    assert "There are 2 users on the server Test Server:" in result
    assert "User1" in result
    assert "Channel 1" in result

    # Test with no users
    payload_no_users = WhoReportPayload(
        server_name="Test Server", total_users=0, grouped_data=[]
    )
    report_no_users = WhoReport(payload=payload_no_users)
    mock_translator.gettext.return_value = (
        "No users found online on server {server_host}."
    )
    result_no_users = format_who_report_to_html(report_no_users, mock_translator)
    assert "No users found online on server Test Server." in result_no_users

    # Test with error
    report_error = WhoReport(error_message="Test Error")
    result_error = format_who_report_to_html(report_error, mock_translator)
    assert result_error == "Test Error"


def test_format_help_text(mock_translator: MagicMock) -> None:
    """Test the format_help_text function."""

    # For regular user
    mock_translator.gettext.return_value = "/who - Show online users."
    result_user = format_help_text(mock_translator, is_admin=False)
    assert "/who" in result_user
    assert "/kick" not in result_user

    # For admin
    mock_translator.gettext.return_value = (
        "/kick - Kick a user from the server (via buttons)."
    )
    result_admin = format_help_text(mock_translator, is_admin=True)
    assert "/kick" in result_admin


def test_format_moderation_prompt(mock_translator: MagicMock) -> None:
    """Test the format_moderation_prompt function."""

    mock_translator.gettext.side_effect = lambda s: s.format(server_host="Test Server")
    result = format_moderation_prompt(AdminCommand.KICK, "Test Server", mock_translator)
    assert "Select a user to kick from Test Server:" in result


def test_format_manage_muted_menu_text(mock_translator: MagicMock) -> None:
    """Test the format_manage_muted_menu_text function."""

    mock_translator.gettext.return_value = "Current mode is Blacklist."
    result = format_manage_muted_menu_text(mock_translator, MuteListMode.blacklist)
    assert "Current mode is Blacklist." in result


def test_format_paginated_list_text(mock_translator: MagicMock) -> None:
    """Test the format_paginated_list_text function."""

    mock_translator.gettext.side_effect = lambda s: s.format(
        current_page=1, total_pages=2, server_host="Test Server"
    )
    result = format_paginated_list_text(
        mock_translator, "Title", 10, 0, 5, "Empty", "Test Server"
    )
    assert "Title on Test Server" in result
    assert "Page 1/2" in result
