"""Custom exception classes for the bot."""


class BotError(Exception):
    """Base class for custom exceptions in the bot."""


class AdminAuthError(BotError):
    """Raised when an admin command fails due to authorization issues."""


class DependencyError(BotError):
    """Base class for dependency-related errors."""


class MissingSettingsError(DependencyError):
    """Raised when settings are not found or of incorrect type."""

    def __init__(
        self, message: str = "Settings not found or of incorrect type in kwargs."
    ) -> None:
        """Initializes the exception with a default message."""
        super().__init__(message)


class NoActiveTeamTalkConnectionError(BotError):
    """Raised when no active TeamTalk connection is available."""


class TeamTalkConnectionError(BotError):
    """Raised when a connection to the TeamTalk server fails."""


class MissingTranslatorError(DependencyError):
    """Raised when the translator is not found or of incorrect type."""

    def __init__(
        self, message: str = "Translator not found or of incorrect type in kwargs."
    ) -> None:
        """Initializes the exception with a default message."""
        super().__init__(message)
