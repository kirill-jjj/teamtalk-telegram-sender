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
    # page: int = 0 # Initial page is always 0, so not strictly needed here if handlers default to 0

# For paginating any user list
class PaginateUsersCallback(CallbackData, prefix="paginate_list"):
    # action: str # Not needed if prefix is specific enough, or use e.g. "page"
    list_type: str  # e.g., "muted", "allowed", "server_users"
    page: int

# For muting/unmuting a specific user from a list
class ToggleMuteSpecificCallback(CallbackData, prefix="toggle_user_mute"): # Prefix "tsum" was example, using actual prefix.
    action: str # As per subtask example, keeping action.
    user_idx: int  # Changed from username/nickname
    current_page: int
    list_type: str  # e.g., "muted", "allowed", "server_users"




# Let's adjust SettingsCallback and LanguageCallback slightly for clarity
# SettingsCallback: for navigating *between* major setting sections
# LanguageCallback: for actions *within* the language section

class SettingsNavCallback(CallbackData, prefix="settings_nav"): # Renamed for clarity
    menu: str # e.g., "main", "language", "subscriptions", "notifications"


# This seems more aligned. Let's re-evaluate prefixes and actions during implementation.
# For now, using the initially defined classes and will adjust if needed during handler refactoring.
# The provided plan is quite specific on callback data values like "settings_language" etc.
# These will become actions in the CallbackData objects.








# Final check on prefixes to avoid collisions:
# "settings_nav" - SettingsCallback
# "lang_set" - LanguageCallback
# "sub_set" - SubscriptionCallback
# "notif_action" - NotificationActionCallback
# "mute_all_toggle" - MuteAllCallback
# "user_list_nav" - UserListCallback
# "paginate_list" - PaginateUsersCallback
# "toggle_user_mute" - ToggleMuteSpecificCallback
# Prefixes look distinct.

print("CallbackData classes defined in bot/telegram_bot/callback_data.py")
