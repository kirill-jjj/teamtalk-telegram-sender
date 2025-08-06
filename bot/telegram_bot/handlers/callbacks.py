"""Main router for aggregating all callback query handlers."""

from aiogram import Router

from bot.telegram_bot.middlewares import ActiveTeamTalkConnectionMiddleware

from .callback_handlers.admin import admin_actions_router
from .callback_handlers.banned_user_actions import banned_user_actions_router
from .callback_handlers.language import language_router
from .callback_handlers.menu_callbacks import admin_menu_callback_router, menu_callback_router
from .callback_handlers.mute import mute_router
from .callback_handlers.navigation import navigation_router
from .callback_handlers.notifications import notifications_router
from .callback_handlers.subscriber_list import subscriber_list_router
from .callback_handlers.subscriber_management import subscriber_management_router
from .callback_handlers.subscription import subscription_router

# Parent router for handlers that require a TeamTalk connection
tt_connected_router = Router(name="tt_connected_router")
tt_connected_router.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))

# Routers that need a TT connection are included here
tt_connected_router.include_router(menu_callback_router)
tt_connected_router.include_router(admin_menu_callback_router)
tt_connected_router.include_router(admin_actions_router)
tt_connected_router.include_router(subscriber_management_router)


# Main router that aggregates all callback handlers
callback_router = Router(name="main_callback_router")

# Include the parent router for TT-connected handlers
callback_router.include_router(tt_connected_router)

# Include other routers that do not require a TT connection check
callback_router.include_router(language_router)
callback_router.include_router(subscription_router)
callback_router.include_router(notifications_router)
callback_router.include_router(mute_router)
callback_router.include_router(navigation_router)
callback_router.include_router(subscriber_list_router)
callback_router.include_router(banned_user_actions_router)
