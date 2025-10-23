"""Tests for TeamTalk formatters."""

from gettext import NullTranslations
from unittest.mock import MagicMock

import pytest

from bot.core.enums import DeeplinkAction
from bot.models import Deeplink
from bot.teamtalk_bot.formatters import format_deeplink_reply


@pytest.fixture
def mock_translator() -> MagicMock:
    translator = MagicMock(spec=NullTranslations)
    translator.gettext.side_effect = lambda x: x  # Simple passthrough
    return translator


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
