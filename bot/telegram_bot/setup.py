from typing import TYPE_CHECKING
from aiogram import Dispatcher # For type hinting dp

if TYPE_CHECKING:
    from sender import Application # For app_callbacks type hint
    from bot.services_container import Services

# Aiogram компоненты
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

# Middlewares
from bot.telegram_bot.middlewares import (
    DbSessionMiddleware,
    UserSettingsMiddleware,
    SubscriptionCheckMiddleware,
    # ApplicationMiddleware, # Will be removed
    ActiveTeamTalkConnectionMiddleware,
    TeamTalkConnectionCheckMiddleware,
    AdminCheckMiddleware
)

# Роутеры
from bot.telegram_bot.handlers.user import user_commands_router
from bot.telegram_bot.handlers.admin import admin_router
from bot.telegram_bot.handlers.callbacks import callback_router
from bot.telegram_bot.handlers.unknown import catch_all_router
from bot.telegram_bot.handlers.callback_handlers.subscriber_actions import subscriber_actions_router


def setup_telegram_dispatcher(dp: Dispatcher, services: "Services", app_callbacks: "Application"):
    """
    Configures the Aiogram Dispatcher with middlewares, routers,
    and lifecycle handlers.
    Dependencies are injected via dp.workflow_data.
    """
    services.logger.info("Setting up Telegram dispatcher...") # Use logger from services

    # Populate workflow_data for DI
    dp["services"] = services
    dp["config"] = services.config
    dp["session_factory"] = services.session_factory # For DbSessionMiddleware
    # Individual caches/components for direct injection if preferred by handlers later
    dp["admin_ids_cache"] = services.admin_ids_cache
    dp["user_settings_cache"] = services.user_settings_cache
    dp["subscribed_users_cache"] = services.subscribed_users_cache
    dp["connections"] = services.connections
    dp["bot_event"] = services.bot_event
    dp["bot_message"] = services.bot_message
    dp["translator_cache"] = services.translator_cache # Though get_translator is preferred
    dp["available_languages"] = services.available_languages


    # Регистрация Middlewares
    # ApplicationMiddleware is removed.
    dp.update.outer_middleware.register(DbSessionMiddleware(services.session_factory))

    # These middlewares will be refactored later to pull dependencies from data dict
    dp.message.middleware(SubscriptionCheckMiddleware())
    dp.callback_query.middleware(SubscriptionCheckMiddleware())

    dp.message.middleware(UserSettingsMiddleware())
    dp.callback_query.middleware(UserSettingsMiddleware())

    # ActiveTeamTalkConnectionMiddleware can be applied to specific routers or globally
    # For now, assuming it's registered generally and handlers decide if they need tt_connection
    # Or it can be applied to specific routers that always need it.
    # Example: user_commands_router.message.middleware(ActiveTeamTalkConnectionMiddleware())
    # Let's keep it general for now, to be refined if needed.
    # It will also be refactored to use data['services']
    dp.message.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
    dp.callback_query.middleware(ActiveTeamTalkConnectionMiddleware(default_server_key=None))


    dp.callback_query.middleware(CallbackAnswerMiddleware())

    # Middleware для проверки админа на конкретных роутерах
    # These will also be refactored to use data['services']
    admin_router.message.middleware(AdminCheckMiddleware())
    subscriber_actions_router.callback_query.middleware(AdminCheckMiddleware())


    # Подключение роутеров
    dp.include_router(user_commands_router)
    dp.include_router(admin_router)
    dp.include_router(callback_router)
    dp.include_router(subscriber_actions_router)
    dp.include_router(catch_all_router)

    # Регистрация хуков жизненного цикла и обработчика ошибок from Application instance
    dp.startup.register(app_callbacks._on_startup_logic)
    dp.shutdown.register(app_callbacks._on_shutdown_logic)
    dp.errors.register(app_callbacks._global_error_handler)

    services.logger.info("Telegram dispatcher configured.")
