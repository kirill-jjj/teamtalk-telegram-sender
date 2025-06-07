# bot/state.py
from typing import Tuple

# This module stores global, mutable application state,
# such as caches and state flags.

# Cache to store usernames of all currently online users.
# Using a set for efficient (O(1)) lookups.
ONLINE_USERS_CACHE: set[str] = set()

# Cache to store all registered user accounts on the server.
# Key - str(username), value - object pytalk.UserAccount.
# This avoids the slow list_user_accounts() call in menus.
USER_ACCOUNTS_CACHE: dict[str, 'pytalk.UserAccount'] = {}

# Cache to store admin rights of users.
# Key - int(user_id), value - Tuple[bool(is_admin), float(timestamp)]
ADMIN_RIGHTS_CACHE: dict[int, Tuple[bool, float]] = {}
ADMIN_CACHE_TTL_SECONDS = 60
