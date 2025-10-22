"""Enums for TeamTalk bot specific types."""

from enum import StrEnum


class PytalkEvent(StrEnum):
    """Enumeration for pytalk event types used in caching."""

    USER_LOGIN = "user_login"
    USER_JOIN = "user_join"
    USER_UPDATE = "user_update"
    USER_LOGOUT = "user_logout"
    USER_ACCOUNT_NEW = "user_account_new"
    USER_ACCOUNT_REMOVE = "user_account_remove"
