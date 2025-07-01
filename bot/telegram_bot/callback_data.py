from aiogram.filters.callback_data import CallbackData
from bot.core.enums import (
    AdminAction,
    SettingsNavAction,
    LanguageAction,
    SubscriptionAction,
    NotificationAction,
    UserListAction,
    PaginateUsersAction,
    ToggleMuteSpecificAction,
    SubscriberListAction
)

# For main settings navigation
class SettingsCallback(CallbackData, prefix="settings_nav"):
    action: SettingsNavAction

# For language selection
class LanguageCallback(CallbackData, prefix="lang_set"):
    action: LanguageAction
    lang_code: str | None = None # e.g., "en", "ru"; None if action is to show menu

# For subscription settings
class SubscriptionCallback(CallbackData, prefix="sub_set"):
    action: SubscriptionAction
    setting_value: str  # e.g., "all", "join_off", "leave_off", "none"

# For NOON toggle, navigating to mute management
class NotificationActionCallback(CallbackData, prefix="notif_action"):
    action: NotificationAction

# For navigating user lists (initial call to display a list)
class UserListCallback(CallbackData, prefix="user_list_nav"):
    action: UserListAction

from bot.models import MuteListMode

# For setting mute list mode
class SetMuteModeCallback(CallbackData, prefix="mute_mode_set"):
    mode: MuteListMode

# For paginating any user list
class PaginateUsersCallback(CallbackData, prefix="paginate_list"):
    list_type: UserListAction
    page: int

# For muting/unmuting a specific user from a list
class ToggleMuteSpecificCallback(CallbackData, prefix="toggle_user_mute"):
    action: ToggleMuteSpecificAction
    user_idx: int
    current_page: int
    list_type: UserListAction

# For Admin actions like kick/ban
class AdminActionCallback(CallbackData, prefix="admin_action"):
    action: AdminAction
    user_id: int

# For subscriber list actions
class SubscriberListCallback(CallbackData, prefix="sub_list"):
    action: SubscriberListAction
    telegram_id: int | None = None  # Present for "delete_subscriber"
    page: int | None = None
