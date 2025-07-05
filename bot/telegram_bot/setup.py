from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sender import Application

# Aiogram компоненты
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

# Middlewares
from bot.telegram_bot.middlewares import (
    DbSessionMiddleware,
    UserSettingsMiddleware,
    SubscriptionCheckMiddleware,
    ApplicationMiddleware,
    ActiveTeamTalkConnectionMiddleware,
    TeamTalkConnectionCheckMiddleware,
    AdminCheckMiddleware
)

# Роутеры
from bot.telegram_bot.handlers.user import user_commands_router
from bot.telegram_bot.handlers.admin import admin_router
from bot.telegram_bot.handlers.callbacks import callback_router
from bot.telegram_bot.handlers.unknown import catch_all_router
# --- ИСПРАВЛЕННЫЙ ИМПОРТ ---
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---
from bot.telegram_bot.handlers.callback_handlers.subscriber_actions import subscriber_actions_router


def setup_telegram_dispatcher(app: "Application"):
    """
    Configures the Aiogram Dispatcher with middlewares, routers,
    and lifecycle handlers.
    """
    app.logger.info("Setting up Telegram dispatcher...")

    # Регистрация Middlewares
    app.dp.update.outer_middleware.register(ApplicationMiddleware(app))
    app.dp.update.outer_middleware.register(DbSessionMiddleware(app.session_factory))

    app.dp.message.middleware(SubscriptionCheckMiddleware())
    app.dp.callback_query.middleware(SubscriptionCheckMiddleware())

    app.dp.message.middleware(UserSettingsMiddleware())
    app.dp.callback_query.middleware(UserSettingsMiddleware())

    # ActiveTeamTalkConnectionMiddleware will be applied to specific routers
    # app.dp.message.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
    # app.dp.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))

    app.dp.callback_query.middleware(CallbackAnswerMiddleware())

    # Middleware для проверки админа на конкретных роутерах
    admin_router.message.middleware(AdminCheckMiddleware())
    subscriber_actions_router.callback_query.middleware(AdminCheckMiddleware())
    # --- ИСПРАВЛЕНИЕ ЗДЕСЬ, чтобы защитить кнопки админа в меню ---
    # menu_callback_router.callback_query.middleware(AdminCheckMiddleware()) # Removed: Handled by main callback_router or within menu_callbacks itself
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---


    # Подключение роутеров
    app.dp.include_router(user_commands_router)
    app.dp.include_router(admin_router)
    app.dp.include_router(callback_router) # menu_callback_router is now included here
    # --- ИСПРАВЛЕННЫЙ РОУТЕР ---
    # app.dp.include_router(menu_callback_router) # Removed: Handled by main callback_router
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
    app.dp.include_router(subscriber_actions_router)
    app.dp.include_router(catch_all_router)

    # Регистрация хуков жизненного цикла и обработчика ошибок
    app.dp.startup.register(app._on_startup_logic)
    app.dp.shutdown.register(app._on_shutdown_logic)
    app.dp.errors.register(app._global_error_handler)

    app.logger.info("Telegram dispatcher configured.")
