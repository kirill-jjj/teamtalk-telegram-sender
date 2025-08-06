"""Sets up the Aiogram Dispatcher with middlewares, routers, and lifecycle handlers."""

from collections.abc import Callable
from gettext import GNUTranslations
import logging
from typing import TYPE_CHECKING

from aiogram import BaseMiddleware, Bot, Dispatcher, html
from aiogram.types import ErrorEvent
from aiogram.types import Message as AiogramMessage
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from dishka import make_async_container
from dishka.integrations.aiogram import FromDishka, setup_dishka

from bot.config import Settings
from bot.core.languages import DEFAULT_LANGUAGE_CODE
from bot.di_providers import AppProvider, RequestProvider
from bot.services.cache_service import CacheService
from bot.telegram_bot.handlers.admin import admin_router
from bot.telegram_bot.handlers.callbacks import callback_router
from bot.telegram_bot.handlers.unknown import catch_all_router
from bot.telegram_bot.handlers.user import user_commands_router
from bot.telegram_bot.middlewares import (
    ActiveTeamTalkConnectionMiddleware,
    SubscriptionCheckMiddleware,
)

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


async def global_error_handler(
    event: ErrorEvent,
    bot: FromDishka[Bot],
    cache: FromDishka[CacheService],
    settings: FromDishka[Settings],
    translator_factory: FromDishka[Callable[[str], GNUTranslations]],
) -> None:
    """Global error handler for uncaught exceptions in Aiogram handlers."""
    escaped_exception_text = html.quote(str(event.exception))
    logger.critical("Unhandled exception in Aiogram handler: %s", event.exception, exc_info=True)

    admin_chat_id_for_error = settings.telegram.admin_chat_id
    admin_lang_code = settings.general.default_lang

    if admin_chat_id_for_error:
        admin_user_settings = cache.get_user_settings(admin_chat_id_for_error)
        if admin_user_settings and admin_user_settings.language_code:
            admin_lang_code = admin_user_settings.language_code

        try:
            admin_critical_translator = translator_factory(admin_lang_code)
            error_text = admin_critical_translator.gettext(
                "<b>Critical error!</b>\n<b>Error type:</b> {error_type}\n<b>Message:</b> {error_message}"
            ).format(error_type=type(event.exception).__name__, error_message=escaped_exception_text)
            await bot.send_message(admin_chat_id_for_error, error_text)
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
        user_settings = cache.get_user_settings(user_id)
        if user_settings and user_settings.language_code:
            lang_code = user_settings.language_code

    translator = translator_factory(lang_code)
    _ = translator.gettext
    user_message_text = _("An unexpected error occurred. The administrator has been notified. Please try again later.")

    if not (user_id and admin_chat_id_for_error and user_id == admin_chat_id_for_error):
        try:
            if update.message:
                await update.message.answer(user_message_text)
            elif update.callback_query and isinstance(update.callback_query.message, AiogramMessage):
                await update.callback_query.message.answer(user_message_text)
            elif user_id:
                await bot.send_message(chat_id=user_id, text=user_message_text)
        except Exception:
            logger.exception("Error sending error message to user %s.", user_id if user_id else "Unknown")


def create_telegram_dispatcher() -> Dispatcher:
    """Creates an Aiogram Dispatcher instance."""
    return Dispatcher()


def setup_telegram_dispatcher(dp: Dispatcher) -> None:
    """Configures the Aiogram Dispatcher with middlewares, routers, and lifecycle handlers."""
    logger.info("Setting up Telegram dispatcher...")

    # Register middlewares on all update types to avoid repetition
    # These will be executed for all incoming updates before they reach handlers
    common_middlewares: list[BaseMiddleware] = [
        SubscriptionCheckMiddleware(),
        ActiveTeamTalkConnectionMiddleware(default_server_key=None),
    ]
    for middleware in common_middlewares:
        dp.update.middleware.register(middleware)

    # Specific middleware for callback queries only
    dp.callback_query.middleware(CallbackAnswerMiddleware())

    container = make_async_container(AppProvider(), RequestProvider())
    setup_dishka(container, router=dp)

    dp.include_router(user_commands_router)
    dp.include_router(admin_router)
    dp.include_router(callback_router)
    dp.include_router(catch_all_router)

    dp.errors.register(global_error_handler)

    logger.info("Telegram dispatcher configured.")
