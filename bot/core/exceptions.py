"""Custom exception classes for the bot."""


class BotError(Exception):
    """Base class for custom exceptions in the bot."""


class AdminAuthError(BotError):
    """Raised when an admin command fails due to authorization issues."""
