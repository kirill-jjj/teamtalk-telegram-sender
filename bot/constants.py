MUTE_ACTION_MUTE = "mute"
MUTE_ACTION_UNMUTE = "unmute"

NOTIFICATION_EVENT_JOIN = "join"
NOTIFICATION_EVENT_LEAVE = "leave"

from bot.core.languages import DEFAULT_LANGUAGE_CODE # Changed import

DEFAULT_LANGUAGE = DEFAULT_LANGUAGE_CODE # Use the new constant

TEAMTALK_PRIVATE_MESSAGE_TYPE = 1

INITIAL_LOGIN_IGNORE_DELAY_SECONDS = 2

TT_HELP_MESSAGE_PART_DELAY = 0.3
TT_MAX_MESSAGE_BYTES = 511

CALLBACK_NICKNAME_MAX_LENGTH = 30
USERS_PER_PAGE = 10 # For pagination in settings menus

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"

DB_MAIN_NAME = "main"


WHO_CHANNEL_ID_ROOT = 1
WHO_CHANNEL_ID_SERVER_ROOT_ALT = 0 # Sometimes used for users not in a specific channel
WHO_CHANNEL_ID_SERVER_ROOT_ALT2 = -1 # Also seen for users not in a specific channel


# --- Parameters ---
DEEPLINK_TOKEN_LENGTH_BYTES = 16

# --- Timeouts and Delays ---
TT_CACHE_SYNC_RETRY_DELAY_SECONDS = 60

# --- Callback Prefixes ---
CB_PREFIX_SETTINGS_NAV = "settings_nav"
CB_PREFIX_LANG_SET = "lang_set"
CB_PREFIX_SUB_SET = "sub_set"
CB_PREFIX_NOTIF_ACTION = "notif_action"
CB_PREFIX_USER_LIST_NAV = "user_list_nav"
CB_PREFIX_MUTE_MODE_SET = "mute_mode_set"
CB_PREFIX_PAGINATE_LIST = "paginate_list"
CB_PREFIX_TOGGLE_USER_MUTE = "toggle_user_mute"
CB_PREFIX_ADMIN_ACTION = "admin_action"
CB_PREFIX_SUB_LIST = "sub_list"
CB_PREFIX_MAIN_MENU = "main_menu"
CB_PREFIX_VIEW_SUB = "view_sub"
CB_PREFIX_SUB_ACTION = "sub_action"
CB_PREFIX_MANAGE_TT_ACC = "manage_tt_acc"
CB_PREFIX_LINK_TT_CHOSEN = "link_tt_chosen"
