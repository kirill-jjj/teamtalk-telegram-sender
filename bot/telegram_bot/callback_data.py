"""Defines Pydantic models for Aiogram CallbackData."""

from aiogram.filters.callback_data import CallbackData

from bot.constants import (
    CB_PREFIX_ADMIN_ACTION,
    CB_PREFIX_LANG_SET,
    CB_PREFIX_LINK_TT_CHOSEN,
    CB_PREFIX_MAIN_MENU,
    CB_PREFIX_MANAGE_TT_ACC,
    CB_PREFIX_MUTE_MODE_SET,
    CB_PREFIX_NOTIF_ACTION,
    CB_PREFIX_PAGINATE_LINKABLE_ACCOUNTS,  # Added here
    CB_PREFIX_PAGINATE_LIST,
    CB_PREFIX_SETTINGS_NAV,
    CB_PREFIX_SUB_ACTION,
    CB_PREFIX_SUB_LIST,
    CB_PREFIX_SUB_SET,
    CB_PREFIX_TOGGLE_USER_MUTE,
    CB_PREFIX_USER_LIST_NAV,
    CB_PREFIX_VIEW_SUB,
)
from bot.core.enums import (
    AdminAction,
    LanguageAction,
    ManageTTAccountAction,
    NotificationAction,
    SettingsNavAction,
    SubscriberAction,
    SubscriberListAction,
    SubscriptionAction,
    ToggleMuteSpecificAction,
    UserListAction,
)
from bot.models import MuteListMode


# For main settings navigation
class SettingsCallback(CallbackData, prefix=CB_PREFIX_SETTINGS_NAV):
    """Callback data for main settings navigation."""

    action: SettingsNavAction


# For language selection
class LanguageCallback(CallbackData, prefix=CB_PREFIX_LANG_SET):
    """Callback data for language selection."""

    action: LanguageAction
    lang_code: str | None = None  # e.g., "en", "ru"; None if action is to show menu


# For subscription settings
class SubscriptionCallback(CallbackData, prefix=CB_PREFIX_SUB_SET):
    """Callback data for subscription settings."""

    action: SubscriptionAction
    setting_value: str  # e.g., "all", "join_off", "leave_off", "none"


# For NOON toggle, navigating to mute management
class NotificationActionCallback(CallbackData, prefix=CB_PREFIX_NOTIF_ACTION):
    """Callback data for notification actions like toggling NOON or managing mutes."""

    action: NotificationAction


# For navigating user lists (initial call to display a list)
class UserListCallback(CallbackData, prefix=CB_PREFIX_USER_LIST_NAV):
    """Callback data for navigating to different user lists."""

    action: UserListAction


# For setting mute list mode
class SetMuteModeCallback(CallbackData, prefix=CB_PREFIX_MUTE_MODE_SET):
    """Callback data for setting the mute list mode (blacklist/whitelist)."""

    mode: MuteListMode


# For paginating any user list
class PaginateUsersCallback(CallbackData, prefix=CB_PREFIX_PAGINATE_LIST):
    """Callback data for paginating user lists."""

    list_type: UserListAction
    page: int


# For muting/unmuting a specific user from a list
class ToggleMuteSpecificCallback(CallbackData, prefix=CB_PREFIX_TOGGLE_USER_MUTE):
    """Callback data for toggling the mute status of a specific user."""

    action: ToggleMuteSpecificAction
    user_idx: int
    current_page: int
    list_type: UserListAction


# For Admin actions like kick/ban
class AdminActionCallback(CallbackData, prefix=CB_PREFIX_ADMIN_ACTION):
    """Callback data for administrator actions like kick/ban."""

    action: AdminAction
    user_id: int


# For subscriber list actions
class SubscriberListCallback(CallbackData, prefix=CB_PREFIX_SUB_LIST):
    """Callback data for actions on the list of subscribers (e.g., delete, paginate)."""

    action: SubscriberListAction
    telegram_id: int | None = None  # Present for "delete_subscriber"
    page: int | None = None


# For main menu commands
class MenuCallback(CallbackData, prefix=CB_PREFIX_MAIN_MENU):
    """Callback data for main menu commands invoked via inline buttons."""

    command: str


# For viewing a specific subscriber's details/actions menu
class ViewSubscriberCallback(CallbackData, prefix=CB_PREFIX_VIEW_SUB):
    """Callback data for viewing a specific subscriber's details menu."""

    telegram_id: int
    page: int  # To return to the correct page of the subscriber list


# For actions within a subscriber's detail menu
class SubscriberActionCallback(CallbackData, prefix=CB_PREFIX_SUB_ACTION):
    """Callback data for actions performed on a specific subscriber from their menu."""

    action: SubscriberAction
    target_telegram_id: int
    page: int  # To return to the main subscriber list page


# For managing a subscriber's TeamTalk account link
class ManageTTAccountCallback(CallbackData, prefix=CB_PREFIX_MANAGE_TT_ACC):
    """Callback data for managing a subscriber's linked TeamTalk account."""

    action: ManageTTAccountAction
    target_telegram_id: int
    page: int  # To return to the main subscriber list page
    linkable_page: int | None = None # Page of the linkable TT accounts list


# For choosing a TT account to link from a list
class LinkTTAccountChosenCallback(CallbackData, prefix=CB_PREFIX_LINK_TT_CHOSEN):
    """Callback data for when a specific TeamTalk account is chosen for linking."""

    tt_username: str  # The TeamTalk username chosen for linking
    target_telegram_id: int  # The Telegram user to link to
    page: int  # Page of the subscriber list to return to, or page of TT user list if that's paginated


# For paginating the list of linkable TT accounts
class PaginateLinkableAccountsCallback(CallbackData, prefix=CB_PREFIX_PAGINATE_LINKABLE_ACCOUNTS):
    """Callback data for paginating the list of TeamTalk accounts available for linking."""

    subscriber_context_page: int  # Original page of the subscriber list (context to return to)
    target_telegram_id: int       # The Telegram user (subscriber) we are linking an account for
    page: int                     # The page of linkable TT accounts to display
