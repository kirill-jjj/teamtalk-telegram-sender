# bot/state.py
from typing import Tuple

# This module stores global, mutable application state,
# such as caches and state flags.

# Cache to store currently online Pytalk User objects, keyed by their user_id.
# Key: user_id (int), Value: pytalk.user.User object.
ONLINE_USERS_CACHE: dict[int, 'pytalk.user.User'] = {}

# Cache to store all registered user accounts on the server.
# Key - str(username), value - object pytalk.UserAccount.
# This avoids the slow list_user_accounts() call in menus.
USER_ACCOUNTS_CACHE: dict[str, 'pytalk.UserAccount'] = {}

# Cache for subscribed user IDs
SUBSCRIBED_USERS_CACHE: set[int] = set()

# Cache for admin user IDs
ADMIN_IDS_CACHE: set[int] = set()
