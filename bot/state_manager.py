# bot/state_manager.py
import time
from typing import Tuple, Set, Dict
import pytalk # For type hint

class StateManager:
    def __init__(self):
        # Cache to store usernames of all currently online users.
        self.online_users: Set[str] = set()

        # Cache to store all registered user accounts on the server.
        self.user_accounts: Dict[str, 'pytalk.UserAccount'] = {}

        # Cache to store admin rights of users.
        self.admin_rights: Dict[int, Tuple[bool, float]] = {}
        self.ADMIN_CACHE_TTL_SECONDS = 60
