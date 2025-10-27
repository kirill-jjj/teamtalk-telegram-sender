"""Tests for TeamTalk formatters."""

from gettext import NullTranslations
from unittest.mock import MagicMock

import pytest

from bot.core.enums import DeeplinkAction
from bot.database.models import Deeplink
from bot.services.schemas import AdminManagementResult, BatchOperationResult
from bot.teamtalk_bot.formatters import (
    _split_text_for_tt,
    format_admin_management_result,
    format_deeplink_reply,
    format_teamtalk_help_message,
    get_server_display_name,
    get_tt_user_display_name,
    get_user_display_channel_name,
)


@pytest.fixture
def mock_translator() -> MagicMock:
    translator = MagicMock(spec=NullTranslations)

    def gettext_side_effect(text: str) -> str:
        # Simple passthrough for most text
        if "{}" in text:
            return text  # Return format strings as is
        return text

    def ngettext_side_effect(singular: str, plural: str, n: int) -> str:
        if "{}" in singular or "{}" in plural:
            return singular if n == 1 else plural
        return singular if n == 1 else plural

    translator.gettext.side_effect = gettext_side_effect
    translator.ngettext.side_effect = ngettext_side_effect
    return translator


# ... (existing tests for format_deeplink_reply)


@pytest.mark.parametrize(
    ("result", "expected_substrings"),
    [
        (
            AdminManagementResult(
                add_result=BatchOperationResult(successful_ids=[1, 2]),
                remove_result=BatchOperationResult(),
                error_messages=[],
            ),
            ["Successfully added 2 admins."],
        ),
        (
            AdminManagementResult(
                add_result=BatchOperationResult(),
                remove_result=BatchOperationResult(successful_ids=[3]),
                error_messages=[],
            ),
            ["Successfully removed 1 admins."],
        ),
        (
            AdminManagementResult(
                add_result=BatchOperationResult(failed_ids=[4, 5]),
                remove_result=BatchOperationResult(),
                error_messages=[],
            ),
            ["Failed to add 2 admins"],
        ),
        (
            AdminManagementResult(
                add_result=BatchOperationResult(),
                remove_result=BatchOperationResult(failed_ids=[6]),
                error_messages=[],
            ),
            ["Failed to remove 1 admins"],
        ),
        (
            AdminManagementResult(
                add_result=BatchOperationResult(successful_ids=[1], failed_ids=[2]),
                remove_result=BatchOperationResult(successful_ids=[3], failed_ids=[4]),
                error_messages=["Initial error"],
            ),
            [
                "Initial error",
                "Successfully added 1 admins.",
                "Failed to add 1 admins",
                "Successfully removed 1 admins.",
                "Failed to remove 1 admins",
            ],
        ),
        (
            AdminManagementResult(
                add_result=BatchOperationResult(),
                remove_result=BatchOperationResult(),
                error_messages=[],
            ),
            ["No valid admin IDs provided"],
        ),
    ],
)
def test_format_admin_management_result(
    result: AdminManagementResult,
    expected_substrings: list[str],
    mock_translator: MagicMock,
) -> None:
    """Test formatting of admin management results."""
    # To make the mock translator behave more like gettext for this specific test
    mock_translator.gettext.side_effect = (
        lambda s: s.replace(
            "{}",
            str(
                len(result.add_result.successful_ids)
                or len(result.add_result.failed_ids)
                or len(result.remove_result.successful_ids)
                or len(result.remove_result.failed_ids)
            ),
        )
        if "{}" in s
        else s
    )

    output = format_admin_management_result(result, mock_translator)

    for substring in expected_substrings:
        assert substring in output


@pytest.mark.parametrize(
    ("text", "max_len", "expected_parts"),
    [
        ("short text", 100, ["short text"]),
        (
            "This is a slightly longer text that needs splitting.",
            20,
            ["This is a slightly ", "longer text that ", "needs splitting."],
        ),
        (
            "Русский текст для проверки разбиения юникода.",
            30,
            ["Русский текст ", "для проверки ", "разбиения ", "юникода."],
        ),
        (
            "A verylongwordthatcannotbesplitbyaspace",
            10,
            ["A ", "verylongwo", "rdthatcann", "otbesplitb", "yaspace"],
        ),
    ],
)
def test_split_text_for_tt(text: str, max_len: int, expected_parts: list[str]) -> None:
    """Test the _split_text_for_tt function."""

    parts = _split_text_for_tt(text, max_len)
    assert parts == expected_parts


@pytest.fixture
def mock_tt_instance() -> MagicMock:
    instance = MagicMock()
    instance.server.get_properties.return_value.server_name = b"Instance Server Name"
    instance.connected = True
    return instance


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.teamtalk.server_name = None
    return settings


@pytest.fixture
def mock_user() -> MagicMock:
    user = MagicMock()
    user.nickname = b"User Nickname"
    user.username = b"User Username"
    return user


def test_get_server_display_name_from_config(
    mock_settings: MagicMock, mock_translator: MagicMock
) -> None:
    mock_settings.teamtalk.server_name = "Config Server Name"
    result = get_server_display_name(None, mock_translator, mock_settings)
    assert result == "Config Server Name"


def test_get_server_display_name_from_instance(
    mock_tt_instance: MagicMock,
    mock_settings: MagicMock,
    mock_translator: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.teamtalk_bot.formatters.ttstr",
        lambda x: x.decode() if isinstance(x, bytes) else str(x),
    )
    result = get_server_display_name(mock_tt_instance, mock_translator, mock_settings)
    assert result == "Instance Server Name"


def test_get_tt_user_display_name_prioritizes_nickname(
    mock_user: MagicMock,
    mock_translator: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bot.teamtalk_bot.formatters.ttstr",
        lambda x: x.decode() if isinstance(x, bytes) else str(x),
    )
    result = get_tt_user_display_name(mock_user, mock_translator)
    assert result == "User Nickname"


def test_get_user_display_channel_name_for_admin(
    mock_user: MagicMock,
    mock_translator: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_user.channel.name = b"Hidden Channel"
    monkeypatch.setattr(
        "bot.teamtalk_bot.formatters.ttstr",
        lambda x: x.decode() if isinstance(x, bytes) else str(x),
    )
    result = get_user_display_channel_name(
        mock_user, is_caller_admin=True, translator=mock_translator
    )
    assert "in Hidden Channel" in result


def test_format_teamtalk_help_message_for_user(mock_translator: MagicMock) -> None:
    """Test help message for a regular user."""

    result = format_teamtalk_help_message(mock_translator, is_admin=False)
    assert "/sub" in result
    assert "/unsub" in result
    assert "/help" in result
    assert "/add_admin" not in result


def test_format_teamtalk_help_message_for_admin(mock_translator: MagicMock) -> None:
    """Test help message for an admin user."""

    result = format_teamtalk_help_message(mock_translator, is_admin=True)
    assert "/sub" in result
    assert "/unsub" in result
    assert "/help" in result
    assert "/add_admin" in result
    assert "/remove_admin" in result


def test_format_deeplink_reply_subscribe(
    mock_translator: MagicMock,
) -> None:
    """Test formatting a subscribe deeplink reply."""
    deeplink = Deeplink(
        token="sub_token",
        action=DeeplinkAction.SUBSCRIBE,
        payload="test_user",
        expiry_time=MagicMock(),
    )
    bot_username = "my_test_bot"

    result = format_deeplink_reply(deeplink, bot_username, mock_translator)

    assert "Click this link to subscribe" in result
    assert f"https://t.me/{bot_username}?start={deeplink.token}" in result


def test_format_deeplink_reply_unsubscribe(
    mock_translator: MagicMock,
) -> None:
    """Test formatting an unsubscribe deeplink reply."""
    deeplink = Deeplink(
        token="unsub_token",
        action=DeeplinkAction.UNSUBSCRIBE,
        expiry_time=MagicMock(),
    )
    bot_username = "my_test_bot"

    result = format_deeplink_reply(deeplink, bot_username, mock_translator)

    assert "Click this link to unsubscribe" in result
    assert f"https://t.me/{bot_username}?start={deeplink.token}" in result


def test_format_deeplink_reply_invalid_action(
    mock_translator: MagicMock,
) -> None:
    """Test formatting a deeplink with an invalid action."""
    deeplink = Deeplink(
        token="invalid_token",
        action="INVALID_ACTION",  # type: ignore[assignment]
        expiry_time=MagicMock(),
    )
    bot_username = "my_test_bot"

    result = format_deeplink_reply(deeplink, bot_username, mock_translator)

    assert "Invalid action for deeplink." in result
