from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sender import Application # Assuming sender.py is in the root and Application is defined there

# Import necessary Aiogram components, middlewares, and routers
# These will be based on what's currently in Application.run()
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from bot.telegram_bot.middlewares import (
    DbSessionMiddleware,
    UserSettingsMiddleware,
    SubscriptionCheckMiddleware,
    ApplicationMiddleware,
    ActiveTeamTalkConnectionMiddleware,
    TeamTalkConnectionCheckMiddleware
)
from bot.telegram_bot.middlewares.admin_check import AdminCheckMiddleware

# Direct imports for routers
from bot.telegram_bot.handlers.user import user_commands_router
from bot.telegram_bot.handlers.admin import admin_router
from bot.telegram_bot.handlers.callback_handlers.notifications import notifications_router
from bot.telegram_bot.handlers.callback_handlers.admin import admin_actions_router
from bot.telegram_bot.handlers.callback_handlers.subscriber_list import subscriber_list_router
from bot.telegram_bot.handlers.callback_handlers.subscriber_actions import subscriber_actions_router
from bot.telegram_bot.handlers.callback_handlers.main_menu import main_menu_router
from bot.telegram_bot.handlers.callback_handlers.language_selection import language_router
from bot.telegram_bot.handlers.error_handler import router as error_handler_router


def setup_telegram_dispatcher(app: "Application"):
    """
    Configures the Aiogram Dispatcher with middlewares, routers,
    and lifecycle handlers.
    """
    app.logger.info("Setting up Telegram dispatcher...")

    # Register middlewares
    app.dp.update.outer_middleware.register(ApplicationMiddleware(app))
    app.dp.update.outer_middleware.register(DbSessionMiddleware(app.session_factory))

    app.dp.message.middleware(SubscriptionCheckMiddleware())
    app.dp.callback_query.middleware(SubscriptionCheckMiddleware())

    app.dp.message.middleware(UserSettingsMiddleware())
    app.dp.callback_query.middleware(UserSettingsMiddleware())

    app.dp.message.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
    app.dp.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))

    app.dp.callback_query.middleware(CallbackAnswerMiddleware())

    app.dp.message.middleware(TeamTalkConnectionCheckMiddleware()) # This was present in my read version
    app.dp.callback_query.middleware(TeamTalkConnectionCheckMiddleware()) # This was present in my read version

    # Apply AdminCheckMiddleware to specific routers
    admin_router.message.middleware(AdminCheckMiddleware())
    admin_actions_router.callback_query.middleware(AdminCheckMiddleware())
    subscriber_list_router.callback_query.middleware(AdminCheckMiddleware())
    subscriber_actions_router.callback_query.middleware(AdminCheckMiddleware())
    main_menu_router.callback_query.middleware(AdminCheckMiddleware())

    # Include routers
    app.dp.include_router(error_handler_router)
    app.dp.include_router(user_commands_router)
    app.dp.include_router(admin_router)
    app.dp.include_router(notifications_router)
    app.dp.include_router(admin_actions_router)
    app.dp.include_router(subscriber_list_router)
    app.dp.include_router(subscriber_actions_router)
    app.dp.include_router(main_menu_router)
    app.dp.include_router(language_router)

    # Register lifecycle and error handlers
    app.dp.startup.register(app._on_startup_logic)
    app.dp.shutdown.register(app._on_shutdown_logic)
    app.dp.errors.register(app._global_error_handler)

    app.logger.info("Telegram dispatcher configured.")
