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

# Note: For simple "back" buttons that just re-display a menu,
# the original menu's main callback can often be reused.
# For example, back to main settings could use SettingsCallback(action="main_menu_display")
# or rely on the cq_back_to_main_settings handler using its own specific SettingsCallback.
# The plan uses "back_to_main_settings" as a string, which implies it might be handled
# by a SettingsCallback(action="back_to_main_settings") or similar.
# Let's assume for now that "back_to_main_settings" is an action within SettingsCallback.

# Example for back to main settings if it's a specific action in SettingsCallback:
# SettingsCallback(action="main_menu") could be what /settings uses.
# SettingsCallback(action="language_menu") could be what "Language" button uses.
# Back buttons could then call SettingsCallback(action="main_menu").
# Or, as per plan, settings_language -> SettingsCallback(action="language") to show language menu.
# And back button from language menu -> SettingsCallback(action="main_menu") to show main settings.
# Let's stick to the plan's implied structure.
# "back_to_main_settings" seems like an action for SettingsCallback.
# "settings_notifications" is also an action for SettingsCallback to show that menu.
# "manage_muted_users" is an action for NotificationActionCallback.
# "back_to_manage_muted_btn" goes to "manage_muted_users" action.
# "back_to_notif_settings_btn" goes to "settings_notifications" action.

# Refined SettingsCallback based on usage for "back" buttons:
# SettingsCallback.action can be:
# "main" (initial display from /settings)
# "show_language_menu"
# "show_subscriptions_menu"
# "show_notifications_menu"
# "back_to_main" (used by sub-menus like language choice to go back to main settings menu)

# Let's adjust SettingsCallback and LanguageCallback slightly for clarity
# SettingsCallback: for navigating *between* major setting sections
# LanguageCallback: for actions *within* the language section

class SettingsNavCallback(CallbackData, prefix="settings_nav"): # Renamed for clarity
    menu: str # e.g., "main", "language", "subscriptions", "notifications"

# LanguageCallback:
# action="show" (passed from SettingsNavCallback(menu="language"))
# action="set", lang_code="en"

# This seems more aligned. Let's re-evaluate prefixes and actions during implementation.
# For now, using the initially defined classes and will adjust if needed during handler refactoring.
# The provided plan is quite specific on callback data values like "settings_language" etc.
# These will become actions in the CallbackData objects.

# Example: SettingsCallback(action="language") -> shows language menu
# LanguageCallback(action="set_lang", lang_code="en") -> sets language to EN

# Callback for "Back to settings menu" can be SettingsCallback(action="main_settings_display")
# Or the handler for settings (user.py) can be seen as the root, and sub-menus use specific callbacks to return to it.
# The plan mentions `back_to_main_settings` callback for the back button from subscription settings.
# This implies a handler that rebuilds the main settings menu.

# Let's assume `SettingsCallback` will have an action like `display_main`
# And `back_to_main_settings` will trigger that.
# `SettingsCallback(action="language")` for the language button.
# `SettingsCallback(action="subscriptions")` for subscriptions button.
# `SettingsCallback(action="notifications")` for notifications button.
# This seems consistent.
# The `cq_back_to_main_settings` handler will need to filter on a specific `SettingsCallback`.
# Let's add a specific action for it in `SettingsCallback`.
# SettingsCallback(action="display_main_menu")
# SettingsCallback(action="display_language_menu")
# SettingsCallback(action="display_subscriptions_menu")
# SettingsCallback(action="display_notifications_menu")

# This is getting too granular for SettingsCallback. Let's use the initial proposal.
# SettingsCallback(action="language") -> means "go to language settings"
# SettingsCallback(action="subscriptions") -> "go to subscription settings"
# SettingsCallback(action="notifications") -> "go to notification settings"
# SettingsCallback(action="back_to_main") -> used by submenus to return to main settings view.

# This structure seems more robust.
# The `user.py` settings handler would display the initial menu.
# Pressing "Language" (SettingsCallback(action="language")) would lead to a handler
# that then displays language choices with LanguageCallback.
# A "Back" button in the language choice menu would use SettingsCallback(action="back_to_main").
# This `back_to_main` action would be handled by a callback that re-renders the main settings menu.

# Let's re-check the plan:
# `BACK_TO_SETTINGS_BTN` has callback `back_to_main_settings`.
# This handler (`cq_back_to_main_settings`) rebuilds the main settings menu.
# So, this implies: `SettingsCallback(action="back_to_main_settings")`.

# Okay, the classes seem fine as initially defined.
# The `action` fields will map to the old string constants.
# `page: int = 0` in UserListCallback seems redundant if handlers default to 0.
# `nickname: str | None = None` in ToggleMuteSpecificCallback is good.
# `action: str` in PaginateUsersCallback and ToggleMuteSpecificCallback can be removed if prefix is unique. Let's keep for now for clarity.

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
