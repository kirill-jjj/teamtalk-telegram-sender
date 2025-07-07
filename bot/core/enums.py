"""Enumerations for various actions and states within the bot."""

from enum import Enum


class AdminAction(Enum):
    """Actions an administrator can perform."""

    KICK = "kick"
    BAN = "ban"


class SettingsNavAction(Enum):
    """Actions for navigating the main settings menu."""

    LANGUAGE = "language"
    SUBSCRIPTIONS = "subscriptions"
    NOTIFICATIONS = "notifications"
    BACK_TO_MAIN = "back_to_main"


class LanguageAction(Enum):
    """Actions related to language settings."""

    SET_LANG = "set_lang"


class SubscriptionAction(Enum):
    """Actions related to subscription settings."""

    SET_SUB = "set_sub"


class NotificationAction(Enum):
    """Actions related to notification settings, like NOON and mute list management."""

    TOGGLE_NOON = "toggle_noon"
    MANAGE_MUTED = "manage_muted"  # Takes to mute management screen


class MuteAllAction(Enum):
    """Actions related to the global mute_all setting (deprecated but kept for enum structure)."""

    TOGGLE_MUTE_ALL = "toggle_mute_all"


class UserListAction(Enum):
    """Actions for displaying different types of user lists."""

    LIST_ALLOWED = "list_allowed"
    LIST_MUTED = "list_muted"
    LIST_ALL_ACCOUNTS = "list_all_accounts"  # For listing all server accounts to mute/unmute


class PaginateUsersAction(Enum):
    """Actions for paginating user lists."""

    PAGE = "page"


class ToggleMuteSpecificAction(Enum):
    """Actions for toggling the mute status of a specific user."""

    TOGGLE_USER = "toggle_user"


class SubscriberListAction(Enum):
    """Actions related to the main subscriber list (e.g., deleting, paginating)."""

    DELETE_SUBSCRIBER = "delete_subscriber"
    PAGE = "page"


class DeeplinkAction(Enum):
    """Actions that can be performed via deeplinks."""

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


class SubscriberAction(str, Enum):
    """Actions that can be performed on a specific subscriber from their details menu."""

    DELETE = "delete"
    BAN = "ban"
    MANAGE_TT_ACCOUNT = "manage_tt"


class ManageTTAccountAction(str, Enum):
    """Actions for managing a subscriber's linked TeamTalk account."""

    UNLINK = "unlink"
    LINK_NEW = "link_new"
