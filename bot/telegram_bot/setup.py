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
from bot.telegram_bot.handlers import (
    user_commands_router,
    admin_router,
    callback_router,
    catch_all_router,
    menu_callback_router, # Make sure this is the correct name if it exists
    subscriber_actions_router # Make sure this is the correct name if it exists
)


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

    app.dp.message.middleware(TeamTalkConnectionCheckMiddleware())
    app.dp.callback_query.middleware(TeamTalkConnectionCheckMiddleware())

    # Include routers
    app.dp.include_router(user_commands_router)
    app.dp.include_router(admin_router)
    app.dp.include_router(callback_router)
    app.dp.include_router(menu_callback_router)
    app.dp.include_router(subscriber_actions_router)
    app.dp.include_router(catch_all_router)

    # Register lifecycle and error handlers
    app.dp.startup.register(app._on_startup_logic)
    app.dp.shutdown.register(app._on_shutdown_logic)
    app.dp.errors.register(app._global_error_handler)

    app.logger.info("Telegram dispatcher configured.")
