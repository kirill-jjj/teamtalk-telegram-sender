# Deeplink actions
ACTION_SUBSCRIBE = "subscribe"
ACTION_UNSUBSCRIBE = "unsubscribe"
ACTION_SUBSCRIBE_AND_LINK_NOON = "subscribe_link_noon"

# User selection callback actions
# CALLBACK_ACTION_ID = "id" # Removed
CALLBACK_ACTION_KICK = "kick"
CALLBACK_ACTION_BAN = "ban"

# Mute actions
MUTE_ACTION_MUTE = "mute"
MUTE_ACTION_UNMUTE = "unmute"

# Notification event types
NOTIFICATION_EVENT_JOIN = "join"
NOTIFICATION_EVENT_LEAVE = "leave"

# Default language
DEFAULT_LANGUAGE = "en"

# TeamTalk message type for private messages
TEAMTALK_PRIVATE_MESSAGE_TYPE = 1

# Delay for ignoring initial user logins after bot login (seconds)
INITIAL_LOGIN_IGNORE_DELAY_SECONDS = 2

# Reconnect/Rejoin constants
RECONNECT_DELAY_SECONDS = 5
RECONNECT_RETRY_SECONDS = 15
RECONNECT_CHECK_INTERVAL_SECONDS = 10
REJOIN_CHANNEL_DELAY_SECONDS = 2
REJOIN_CHANNEL_RETRY_SECONDS = 3
REJOIN_CHANNEL_MAX_ATTEMPTS = 3
REJOIN_CHANNEL_FAIL_WAIT_SECONDS = 20
TT_HELP_MESSAGE_PART_DELAY = 0.3
TT_MAX_MESSAGE_BYTES = 511

# Minimum arguments for env path
MIN_ARGS_FOR_ENV_PATH = 2

# Callback data limits
CALLBACK_NICKNAME_MAX_LENGTH = 30
USERS_PER_PAGE = 10 # For pagination in settings menus

# Logging
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"

# Database
DEFAULT_DATABASE_FILE = "bot_data.db"
DB_MAIN_NAME = "main"

# TeamTalk Client
DEFAULT_TT_CLIENT_NAME = "TTTM"
DEFAULT_TT_STATUS_TEXT = ""
DEFAULT_TT_PORT = 10333

# Deeplink Expiry
DEEPLINK_EXPIRY_MINUTES = 5

# Who command
WHO_CHANNEL_ID_ROOT = 1
WHO_CHANNEL_ID_SERVER_ROOT_ALT = 0 # Sometimes used for users not in a specific channel
WHO_CHANNEL_ID_SERVER_ROOT_ALT2 = -1 # Also seen for users not in a specific channel
