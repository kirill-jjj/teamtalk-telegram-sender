from aiogram.filters.callback_data import CallbackData

# For main settings navigation
class SettingsCallback(CallbackData, prefix="settings_nav"):
    action: str  # e.g., "language", "subscriptions", "notifications", "back_to_main"

# For language selection
class LanguageCallback(CallbackData, prefix="lang_set"):
    action: str  # e.g., "set_lang", "show_lang_menu" (if "settings_language" was just to show menu)
    lang_code: str | None = None # e.g., "en", "ru"; None if action is to show menu

# For subscription settings
class SubscriptionCallback(CallbackData, prefix="sub_set"):
    action: str  # e.g., "set_sub"
    setting_value: str  # e.g., "all", "join_off", "leave_off", "none"

# For NOON toggle, navigating to mute management
class NotificationActionCallback(CallbackData, prefix="notif_action"):
    action: str  # e.g., "toggle_noon", "manage_muted"

# For toggling Mute All
class MuteAllCallback(CallbackData, prefix="mute_all_toggle"):
    action: str  # e.g., "toggle_mute_all" (could be boolean if only one action)

# For navigating user lists (initial call to display a list)
class UserListCallback(CallbackData, prefix="user_list_nav"):
    action: str  # e.g., "list_muted", "list_allowed", "list_server_users"

# For paginating any user list
class PaginateUsersCallback(CallbackData, prefix="paginate_list"):
    list_type: str  # e.g., "muted", "allowed", "server_users"
    page: int

# For muting/unmuting a specific user from a list
class ToggleMuteSpecificCallback(CallbackData, prefix="toggle_user_mute"):
    action: str # As per subtask example, keeping action.
    username_hash: str # Changed from user_idx: int
    current_page: int
    list_type: str  # e.g., "muted", "allowed", "server_users"
