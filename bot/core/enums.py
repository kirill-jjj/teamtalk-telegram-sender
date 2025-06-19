from enum import Enum

class AdminAction(Enum):
    KICK = "kick"
    BAN = "ban"

class SettingsNavAction(Enum):
    LANGUAGE = "language"
    SUBSCRIPTIONS = "subscriptions"
    NOTIFICATIONS = "notifications"
    BACK_TO_MAIN = "back_to_main"

class LanguageAction(Enum):
    SET_LANG = "set_lang"

class SubscriptionAction(Enum):
    SET_SUB = "set_sub"

class NotificationAction(Enum):
    TOGGLE_NOON = "toggle_noon"
    MANAGE_MUTED = "manage_muted" # Takes to mute management screen

class MuteAllAction(Enum):
    TOGGLE_MUTE_ALL = "toggle_mute_all"

class UserListAction(Enum):
    LIST_ALLOWED = "list_allowed"
    LIST_MUTED = "list_muted"
    LIST_ALL_ACCOUNTS = "list_all_accounts" # For listing all server accounts to mute/unmute

class PaginateUsersAction(Enum):
    PAGE = "page"

class ToggleMuteSpecificAction(Enum):
    TOGGLE_USER = "toggle_user"

class SubscriberListAction(Enum):
    DELETE_SUBSCRIBER = "delete_subscriber"
    PAGE = "page"

class DeeplinkAction(Enum):
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    SUBSCRIBE_AND_LINK_NOON = "subscribe_link_noon"
