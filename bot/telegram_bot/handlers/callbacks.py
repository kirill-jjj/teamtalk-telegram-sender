from aiogram import Router

from .callback_handlers.admin import admin_actions_router
from .callback_handlers.language import language_router
from .callback_handlers.subscription import subscription_router
from .callback_handlers.notifications import notifications_router
from .callback_handlers.mute import mute_router
from .callback_handlers.navigation import navigation_router
from .callback_handlers.subscriber_list import subscriber_list_router

# This is the main router for all callback queries.
# It aggregates all specialized callback routers from the callback_handlers directory.
callback_router = Router(name="main_callback_router")

# Include all the modular routers
callback_router.include_router(admin_actions_router)
callback_router.include_router(language_router)
callback_router.include_router(subscription_router)
callback_router.include_router(notifications_router)
callback_router.include_router(mute_router)
callback_router.include_router(navigation_router)
callback_router.include_router(subscriber_list_router)

# Ensure no old handler code remains in this file.
# All logic previously in this file should now be in the respective
# modules within the callback_handlers directory or in _helpers.py.
