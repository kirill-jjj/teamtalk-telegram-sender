from enum import Enum

class AdminAction(str, Enum):
    KICK = "kick"
    BAN = "ban"

class SettingsNavAction(str, Enum):
    LANGUAGE = "language"
    SUBSCRIPTIONS = "subscriptions"
    NOTIFICATIONS = "notifications"
    BACK_TO_MAIN = "back_to_main" # Used in keyboards to go back to main settings

class LanguageAction(str, Enum):
    SET_LANG = "set_lang"

class SubscriptionAction(str, Enum):
    SET_SUB = "set_sub"

class NotificationAction(str, Enum):
    TOGGLE_NOON = "toggle_noon"
    MANAGE_MUTED = "manage_muted" # Takes to mute management screen

class MuteAllAction(str, Enum):
    TOGGLE_MUTE_ALL = "toggle_mute_all"

class UserListAction(str, Enum):
    LIST_ALLOWED = "list_allowed"
    LIST_MUTED = "list_muted"
    LIST_ALL_ACCOUNTS = "list_all_accounts" # For listing all server accounts to mute/unmute

class PaginateUsersAction(str, Enum):
    # Assuming pagination might have generic "prev", "next" if not specific to list_type
    # For now, specific pagination is handled within callbacks like SubscriberListCallback's "page"
    # If a generic one emerges, add it here. For now, this might be empty or not used directly
    # if specific list_types (like 'subscriber_page') handle their own.
    # Let's check SubscriberListCallback, it uses "page".
    PAGE = "page" # Generic enough if used by multiple pagination scenarios

class ToggleMuteSpecificAction(str, Enum):
    TOGGLE_USER = "toggle_user" # Toggles mute status for a specific user from a list

class SubscriberListAction(str, Enum):
    DELETE_SUBSCRIBER = "delete_subscriber"
    PAGE = "page" # Pagination specific to subscriber list

class DeeplinkAction(str, Enum):
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    SUBSCRIBE_AND_LINK_NOON = "subscribe_link_noon"

# Add other Enums as they are identified.
# Example: Potentially for notification settings values if they are strings
# class NotificationSettingValue(str, Enum):
#     ALL = "all"
#     LEAVE_OFF = "leave_off"
#     JOIN_OFF = "join_off"
#     NONE = "none"
# This one (NotificationSettingValue) is already handled by database.models.NotificationSetting,
# which is an IntEnum. So, no string enum needed here unless direct string comparison is preferred over IntEnum.value.
# The current plan refers to database.models.NotificationSetting for subscription settings, so this string version is not needed.
