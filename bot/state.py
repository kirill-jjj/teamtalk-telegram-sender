# bot/state.py

# This module stores global, mutable application state,
# such as caches and state flags.

# Cache to store usernames of all currently online users.
# Using a set for efficient (O(1)) lookups.
ONLINE_USERS_CACHE: set[str] = set()
