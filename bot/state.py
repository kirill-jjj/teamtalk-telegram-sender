# bot/state.py
from typing import Tuple

# This module stores global, mutable application state,
# such as caches and state flags.

# Cache to store usernames of currently online users and their active session count.
# Key: username (str), Value: session_count (int).
ONLINE_USERS_CACHE: dict[str, int] = {}

# Cache to store all registered user accounts on the server.
# Key - str(username), value - object pytalk.UserAccount.
# This avoids the slow list_user_accounts() call in menus.
USER_ACCOUNTS_CACHE: dict[str, 'pytalk.UserAccount'] = {}

# Cache to store admin rights of users.
# Key - int(user_id), value - Tuple[bool(is_admin), float(timestamp)]
ADMIN_RIGHTS_CACHE: dict[int, Tuple[bool, float]] = {}
ADMIN_CACHE_TTL_SECONDS = 60
