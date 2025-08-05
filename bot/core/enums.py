"""Enumerations for various actions and states within the bot."""

from enum import Enum


class AdminCommand(Enum):
    """Admin commands on TeamTalk users."""

    KICK = "kick"
    BAN = "ban"


class SettingsNavAction(Enum):
    """Actions for navigating the main settings menu."""

    LANGUAGE = "language"
    SUBSCRIPTIONS = "subscriptions"
    NOTIFICATIONS = "notifications"
    BACK_TO_MAIN = "back_to_main"


class LanguageChoice(Enum):
    """Actions related to language settings."""

    SET_LANG = "set_lang"


class SubscriptionCommand(Enum):
    """Commands related to subscription settings."""

    SET_SUB = "set_sub"


class NotificationControl(Enum):
    """Actions related to notification settings, like NOON and mute list management."""

    TOGGLE_NOON = "toggle_noon"
    MANAGE_MUTED = "manage_muted"  # Takes to mute management screen


class UserListAction(Enum):
    """Actions for displaying different types of user lists."""

    LIST_ALLOWED = "list_allowed"
    LIST_MUTED = "list_muted"
    LIST_ALL_ACCOUNTS = "list_all_accounts"  # For listing all server accounts to mute/unmute


class PaginateUsersAction(Enum):
    """Actions for paginating user lists."""

    PAGE = "page"


class ToggleMuteUser(Enum):
    """Actions for toggling the mute status of a specific user."""

    EXECUTE = "toggle_user"


class SubscriberListAction(Enum):
    """Actions related to the main subscriber list (e.g., deleting, paginating)."""

    DELETE_SUBSCRIBER = "delete_subscriber"
    PAGE = "page"


class DeeplinkAction(Enum):
    """Actions that can be performed via deeplinks."""

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


class SubscriberCommand(str, Enum):
    """Actions that can be performed on a specific subscriber from their details menu."""

    DELETE = "delete"
    BAN = "ban"
    UNBAN = "unban"
    MANAGE_TT_ACCOUNT = "manage_tt"
    ADMIN_SET_LANGUAGE = "admin_set_language"
    ADMIN_TOGGLE_NOON = "admin_toggle_noon"
    ADMIN_SET_NOTIF_PREF = "admin_set_notification_preferences"  # longer for clarity
    ADMIN_SET_MUTE_MODE = "admin_set_mute_mode"
    ADMIN_VIEW_MUTE_LIST = "admin_view_mute_list"


class ManageTTAccountAction(str, Enum):
    """Actions for managing a subscriber's linked TeamTalk account."""

    UNLINK = "unlink"
    LINK_NEW = "link_new"


class Actor(str, Enum):
    """Represents the actor performing an action, for logging and context."""

    USER = "user"
    ADMIN = "admin"
