"""Main application entry point for the TeamTalk Telegram Sender bot."""

import argparse
import asyncio
import logging
import traceback
from types import ModuleType  # For uvloop typing

from aiogram import Bot, Dispatcher
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from dishka import make_async_container
from dishka.integrations.aiogram import AiogramProvider, setup_dishka

from bot.config import Settings
from bot.di_providers import AppProvider, RequestProvider
from bot.logging_setup import setup_logging
from bot.telegram_bot.handlers.admin import admin_router
from bot.telegram_bot.handlers.callbacks import callback_router
from bot.telegram_bot.handlers.unknown import catch_all_router
from bot.telegram_bot.handlers.user import user_commands_router
from bot.telegram_bot.middlewares import (
    ActiveTeamTalkConnectionMiddleware,
    SubscriptionCheckMiddleware,
)
from bot.telegram_bot.middlewares.dishka_inject import DishkaInjectMiddleware

uvloop: ModuleType | None = None
try:
    import uvloop as uvloop_module

    uvloop = uvloop_module
except ImportError:
    pass  # uvloop remains None

logger = logging.getLogger(__name__)


class Application:
    """Main application class orchestrating the bot's lifecycle and components."""

    def __init__(self, app_config_instance: Settings) -> None:
        """Initializes the Application.

        Args:
            app_config_instance: The loaded application settings.
        """
        self.app_config = app_config_instance
        self.logger = setup_logging()
        self.dp = Dispatcher()

    async def run(self) -> None:
        """Sets up and runs the main application event loops."""
        self.logger.info("Application starting...")

        # Register middlewares
        self.dp.update.middleware.register(DishkaInjectMiddleware())
        self.dp.update.middleware.register(SubscriptionCheckMiddleware())
        self.dp.update.middleware.register(
            ActiveTeamTalkConnectionMiddleware(default_server_key=None)
        )
        self.dp.callback_query.middleware(CallbackAnswerMiddleware())

        # Create and set up dishka
        app_provider = AppProvider()
        app_provider.dispatcher = self.dp
        container = make_async_container(
            app_provider, RequestProvider(), AiogramProvider()
        )
        setup_dishka(container, router=self.dp)

        # Include routers
        self.dp.include_router(user_commands_router)
        self.dp.include_router(admin_router)
        self.dp.include_router(callback_router)
        self.dp.include_router(catch_all_router)

        self.logger.info("Starting Telegram polling...")
        try:
            bot = await container.get(Bot)
            await self.dp.start_polling(bot)
        finally:
            await container.close()
            self.logger.info("Application finished.")


def main_cli() -> None:
    """Main command-line interface function to start the bot."""
    parser = argparse.ArgumentParser(description="TeamTalk Telegram Sender Bot")
    parser.add_argument(
        "--config",
        type=str,
        default="config.toml",
        help="Path to the TOML configuration file",
    )
    args, _ = parser.parse_known_args()

    try:
        print(f"Loading configuration from: {args.config}")
        app_config_instance = Settings.from_toml(args.config)

        if uvloop:
            uvloop.install()
            print("uvloop installed and used.")
        else:
            print("uvloop not found, using default asyncio event loop.")

        app = Application(app_config_instance)
        asyncio.run(app.run())

    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped by user.")
    except (ValueError, KeyError) as config_error:
        print(f"CRITICAL: Configuration Error: {config_error}.")
        traceback.print_exc()
    except Exception as e:
        print(f"CRITICAL: An unexpected critical error occurred: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main_cli()
