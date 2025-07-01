import pytalk

# This module stores global, mutable application state,
# such as caches and state flags.

# Cache to store currently online Pytalk User objects, keyed by their user_id.
ONLINE_USERS_CACHE: dict[int, 'pytalk.user.User'] = {}

# Cache to store all registered user accounts on the server.
# This avoids the slow list_user_accounts() call in menus.
USER_ACCOUNTS_CACHE: dict[str, 'pytalk.UserAccount'] = {}

SUBSCRIBED_USERS_CACHE: set[int] = set()

ADMIN_IDS_CACHE: set[int] = set()
