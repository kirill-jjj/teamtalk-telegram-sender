from aiogram.filters.callback_data import CallbackData
from bot.core.enums import (
    AdminAction,
    SettingsNavAction,
    LanguageAction,
    SubscriptionAction,
    NotificationAction,
    UserListAction,
    ToggleMuteSpecificAction,
    SubscriberListAction,
    SubscriberAction, # <-- Добавьте новый Enum
    ManageTTAccountAction
)
from bot.models import MuteListMode
from bot.constants import (
    CB_PREFIX_SETTINGS_NAV,
    CB_PREFIX_LANG_SET,
    CB_PREFIX_SUB_SET,
    CB_PREFIX_NOTIF_ACTION,
    CB_PREFIX_USER_LIST_NAV,
    CB_PREFIX_MUTE_MODE_SET,
    CB_PREFIX_PAGINATE_LIST,
    CB_PREFIX_TOGGLE_USER_MUTE,
    CB_PREFIX_ADMIN_ACTION,
    CB_PREFIX_SUB_LIST,
    CB_PREFIX_MAIN_MENU,
    CB_PREFIX_VIEW_SUB,
    CB_PREFIX_SUB_ACTION,
    CB_PREFIX_MANAGE_TT_ACC,
    CB_PREFIX_LINK_TT_CHOSEN,
)

# For main settings navigation
class SettingsCallback(CallbackData, prefix=CB_PREFIX_SETTINGS_NAV):
    action: SettingsNavAction

# For language selection
class LanguageCallback(CallbackData, prefix=CB_PREFIX_LANG_SET):
    action: LanguageAction
    lang_code: str | None = None # e.g., "en", "ru"; None if action is to show menu

# For subscription settings
class SubscriptionCallback(CallbackData, prefix=CB_PREFIX_SUB_SET):
    action: SubscriptionAction
    setting_value: str  # e.g., "all", "join_off", "leave_off", "none"

# For NOON toggle, navigating to mute management
class NotificationActionCallback(CallbackData, prefix=CB_PREFIX_NOTIF_ACTION):
    action: NotificationAction

# For navigating user lists (initial call to display a list)
class UserListCallback(CallbackData, prefix=CB_PREFIX_USER_LIST_NAV):
    action: UserListAction

# For setting mute list mode
class SetMuteModeCallback(CallbackData, prefix=CB_PREFIX_MUTE_MODE_SET):
    mode: MuteListMode

# For paginating any user list
class PaginateUsersCallback(CallbackData, prefix=CB_PREFIX_PAGINATE_LIST):
    list_type: UserListAction
    page: int

# For muting/unmuting a specific user from a list
class ToggleMuteSpecificCallback(CallbackData, prefix=CB_PREFIX_TOGGLE_USER_MUTE):
    action: ToggleMuteSpecificAction
    user_idx: int
    current_page: int
    list_type: UserListAction

# For Admin actions like kick/ban
class AdminActionCallback(CallbackData, prefix=CB_PREFIX_ADMIN_ACTION):
    action: AdminAction
    user_id: int

# For subscriber list actions
class SubscriberListCallback(CallbackData, prefix=CB_PREFIX_SUB_LIST):
    action: SubscriberListAction
    telegram_id: int | None = None  # Present for "delete_subscriber"
    page: int | None = None

# For main menu commands
class MenuCallback(CallbackData, prefix=CB_PREFIX_MAIN_MENU):
    command: str

# For viewing a specific subscriber's details/actions menu
class ViewSubscriberCallback(CallbackData, prefix=CB_PREFIX_VIEW_SUB):
    telegram_id: int
    page: int # To return to the correct page of the subscriber list

# For actions within a subscriber's detail menu
class SubscriberActionCallback(CallbackData, prefix=CB_PREFIX_SUB_ACTION):
    action: SubscriberAction  # <-- Укажите тип Enum вместо str
    target_telegram_id: int
    page: int # To return to the main subscriber list page

# For managing a subscriber's TeamTalk account link
class ManageTTAccountCallback(CallbackData, prefix=CB_PREFIX_MANAGE_TT_ACC):
    action: ManageTTAccountAction  # <-- Укажите тип Enum
    target_telegram_id: int
    page: int # To return to the main subscriber list page

# For choosing a TT account to link from a list
class LinkTTAccountChosenCallback(CallbackData, prefix=CB_PREFIX_LINK_TT_CHOSEN):
    tt_username: str # The TeamTalk username chosen for linking
    target_telegram_id: int # The Telegram user to link to
    page: int # Page of the subscriber list to return to, or page of TT user list if that's paginated
