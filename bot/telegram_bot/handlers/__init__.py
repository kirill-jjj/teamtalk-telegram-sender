from aiogram import Router

# Import routers from individual handler files
from .user import user_commands_router
from .settings import settings_router
from .admin import admin_router
from .callbacks import callback_router
from .unknown import catch_all_router # Renamed from unknown_router for clarity

# You can create a main router here to include all others,
# or include them directly in the dispatcher in main.py.
# For simplicity, we'll import them and they can be included in main.py.

__all__ = [
    "user_commands_router",
    "settings_router",
    "admin_router",
    "callback_router",
    "catch_all_router",
