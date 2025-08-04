"""Sets up the Aiogram Dispatcher with middlewares, routers, and lifecycle handlers."""

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from aiogram import BaseMiddleware, Dispatcher, html
from aiogram.types import ErrorEvent
from aiogram.types import Message as AiogramMessage
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from bot.config import Settings
from bot.core.languages import DEFAULT_LANGUAGE_CODE
from bot.telegram_bot.handlers.admin import admin_router
from bot.telegram_bot.handlers.callback_handlers.admin import admin_actions_router
from bot.telegram_bot.handlers.callback_handlers.subscriber_actions import (
    subscriber_actions_router,
)
from bot.telegram_bot.handlers.callbacks import callback_router
from bot.telegram_bot.handlers.unknown import catch_all_router

# Routers
from bot.telegram_bot.handlers.user import user_commands_router

# Middlewares
from bot.telegram_bot.middlewares import (
    ActiveTeamTalkConnectionMiddleware,
    AdminCheckMiddleware,
    DbSessionMiddleware,
    I18nMiddleware,
    SubscriptionCheckMiddleware,
    UserSettingsMiddleware,
)

if TYPE_CHECKING:
    from bot.services_container import Services


# --- Application Lifecycle and Error Handling Functions ---
async def on_startup_logic(dispatcher: Dispatcher, services: "Services") -> None:
    """Orchestrates the application's startup sequence."""
    logger = services.logger
    logger.info("Application startup...")

    # Initialize TeamTalk bot connection
    await services.init_teamtalk(dispatcher)

    # Load all necessary data from the database into the cache
    await services.load_all_caches()

    # Ensure the main admin from the config is set up
    await services.ensure_main_admin()

    # Set the bot's commands in Telegram
    await services.set_telegram_commands()

    logger.info("Final admin count after startup: %s", services.cache.get_admin_count())
    logger.info("Application startup sequence complete.")


async def on_shutdown_logic(dispatcher: Dispatcher, services: "Services") -> None:
    """Handles application shutdown logic."""
    logger = services.logger
    logger.warning("Application shutting down...")

    teamtalk_task = dispatcher.workflow_data.get("teamtalk_task")
    if teamtalk_task and not teamtalk_task.done():
        logger.info("Cancelling Pytalk main event loop task...")
        teamtalk_task.cancel()
        try:
            await teamtalk_task
        except asyncio.CancelledError:
            logger.info("Pytalk main event loop task cancelled successfully.")
        except Exception:
            logger.exception("Error awaiting cancelled Pytalk task.")
    elif teamtalk_task:
        logger.info("Pytalk main event loop task was already done.")
    else:
        logger.info("No Pytalk main event loop task found to cancel.")

    logger.info("Disconnecting TeamTalk instances...")
    for conn_key, connection in services.connections.items():
        logger.info("Shutting down connection for %s...", conn_key)
        await connection.disconnect_instance()
    logger.info("All TeamTalk connections processed for shutdown.")

    if hasattr(services.bot_event, "session") and services.bot_event.session:
        await services.bot_event.session.close()
    if (
        services.bot_message
        and hasattr(services.bot_message, "session")
        and services.bot_message.session
        and services.bot_message is not services.bot_event
    ):
        await services.bot_message.session.close()
    logger.info("Telegram bot sessions closed.")
    logger.info("Application shutdown sequence complete.")


async def global_error_handler(event: ErrorEvent, services: "Services", app_config: "Settings") -> None:
    """Global error handler for uncaught exceptions in Aiogram handlers."""
    logger = services.logger
    escaped_exception_text = html.quote(str(event.exception))
    logger.critical("Unhandled exception in Aiogram handler: %s", event.exception, exc_info=True)

    admin_chat_id_for_error = app_config.telegram.admin_chat_id
    admin_lang_code = app_config.general.default_lang

    if admin_chat_id_for_error:
        admin_user_settings = services.cache.get_user_settings(admin_chat_id_for_error)
        if admin_user_settings and admin_user_settings.language_code:
            admin_lang_code = admin_user_settings.language_code

        try:
            admin_critical_translator = services.get_translator(admin_lang_code)
            error_text = admin_critical_translator.gettext(
                "<b>Critical error!</b>\n<b>Error type:</b> {error_type}\n<b>Message:</b> {error_message}"
            ).format(error_type=type(event.exception).__name__, error_message=escaped_exception_text)
            await services.bot_event.send_message(admin_chat_id_for_error, error_text)
        except Exception:
            logger.exception(
                "Error sending critical error message to admin chat %s.",
                admin_chat_id_for_error,
            )

    update = event.update
    user_id = None
    if update.message and update.message.from_user:
        user_id = update.message.from_user.id
    elif update.callback_query and update.callback_query.from_user:
        user_id = update.callback_query.from_user.id

    lang_code = DEFAULT_LANGUAGE_CODE
    if user_id:
        user_settings = services.cache.get_user_settings(user_id)
        if user_settings and user_settings.language_code:
            lang_code = user_settings.language_code

    translator = services.get_translator(lang_code)
    _ = translator.gettext
    user_message_text = _("An unexpected error occurred. The administrator has been notified. Please try again later.")

    if not (user_id and admin_chat_id_for_error and user_id == admin_chat_id_for_error):
        try:
            if update.message:
                await update.message.answer(user_message_text)
            elif update.callback_query and isinstance(update.callback_query.message, AiogramMessage):
                await update.callback_query.message.answer(user_message_text)
            elif user_id:
                await services.bot_event.send_message(chat_id=user_id, text=user_message_text)
        except Exception:
            logger.exception("Error sending error message to user %s.", user_id if user_id else "Unknown")


def create_telegram_dispatcher() -> Dispatcher:
    """Creates an Aiogram Dispatcher instance."""
    return Dispatcher()


def setup_telegram_dispatcher(dp: Dispatcher, services: "Services") -> None:
    """Configures the Aiogram Dispatcher with middlewares, routers, and lifecycle handlers.

    Dependencies are injected via dp.workflow_data.
    """
    services.logger.info("Setting up Telegram dispatcher...")

    dp["services"] = services
    dp["config"] = services.config
    dp["session_factory"] = services.session_factory
    dp["connections"] = services.connections
    dp["bot_event"] = services.bot_event
    dp["bot_message"] = services.bot_message
    dp["translator_cache"] = services.translator_cache
    dp["available_languages"] = services.available_languages

    dp.update.outer_middleware.register(DbSessionMiddleware(services.session_factory))

    # Register middlewares on all update types to avoid repetition
    # These will be executed for all incoming updates before they reach handlers
    common_middlewares: list[BaseMiddleware] = [
        SubscriptionCheckMiddleware(),
        UserSettingsMiddleware(),
        I18nMiddleware(),
        ActiveTeamTalkConnectionMiddleware(default_server_key=None),
    ]
    for middleware in common_middlewares:
        dp.update.middleware.register(middleware)

    # Specific middleware for callback queries only
    dp.callback_query.middleware(CallbackAnswerMiddleware())

    admin_router.message.middleware(AdminCheckMiddleware())
    # admin_actions_router is imported at the top-level now.
    admin_actions_router.callback_query.middleware(AdminCheckMiddleware())
    subscriber_actions_router.callback_query.middleware(AdminCheckMiddleware())

    dp.include_router(user_commands_router)
    dp.include_router(admin_router)
    dp.include_router(callback_router)
    dp.include_router(catch_all_router)

    # Register lifecycle hooks and error handler using new local functions
    # services.config is passed as app_config
    app_config = services.config
    dp.startup.register(partial(on_startup_logic, services=services))
    dp.shutdown.register(partial(on_shutdown_logic, services=services))
    dp.errors.register(partial(global_error_handler, services=services, app_config=app_config))

    services.logger.info("Telegram dispatcher configured.")
