"""Tests for custom exceptions."""

import pytest

from bot.core.exceptions import (
    AdminAuthError,
    BotError,
    MissingSettingsError,
    MissingTranslatorError,
    NoActiveTeamTalkConnectionError,
    SessionNotAvailableError,
    TeamTalkConnectionError,
)


@pytest.mark.parametrize(
    ("exception_class", "message"),
    [
        (BotError, "Base class for custom exceptions in the bot."),
        (
            AdminAuthError,
            "Raised when an admin command fails due to authorization issues.",
        ),
        (
            MissingSettingsError,
            "Settings not found or of incorrect type in kwargs.",
        ),
        (
            NoActiveTeamTalkConnectionError,
            "Raised when no active TeamTalk connection is available.",
        ),
        (
            TeamTalkConnectionError,
            "Raised when a connection to the TeamTalk server fails.",
        ),
        (
            MissingTranslatorError,
            "Translator not found or of incorrect type in kwargs.",
        ),
        (
            SessionNotAvailableError,
            "Session not available. The UoW must be entered first.",
        ),
    ],
)
def test_exceptions_with_docstring_message(
    exception_class: type[BotError], message: str
) -> None:
    """Test that exceptions use their docstring as the message."""
    with pytest.raises(exception_class) as exc_info:
        raise exception_class()
    assert str(exc_info.value) == message


@pytest.mark.parametrize(
    "exception_class",
    [
        MissingSettingsError,
        MissingTranslatorError,
        SessionNotAvailableError,
    ],
)
def test_exceptions_with_custom_message(exception_class: type[BotError]) -> None:
    """Test that a custom message can be passed to exceptions that support it."""
    custom_message = "This is a custom message."
    with pytest.raises(exception_class) as exc_info:
        raise exception_class(custom_message)
    assert str(exc_info.value) == custom_message
