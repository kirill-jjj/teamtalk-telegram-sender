
from .user import user_commands_router
from .admin import admin_router
from .callbacks import callback_router
from .unknown import catch_all_router

__all__ = [
    "user_commands_router",
    "admin_router",
    "callback_router",
    "catch_all_router",
]
