"""Main application entry point for the TeamTalk Telegram Sender bot."""

import argparse
import asyncio
import logging
import traceback
from types import ModuleType  # For uvloop typing

from aiogram import Dispatcher
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from dishka import make_async_container
from dishka.integrations.aiogram import AiogramProvider, setup_dishka

from bot.config import Settings
from bot.di_providers import AppProvider, RequestProvider
from bot.lifecycle import on_startup
from bot.logging_setup import setup_logging
from bot.telegram_bot.handlers.admin import admin_router
from bot.telegram_bot.handlers.callbacks import callback_router
from bot.telegram_bot.handlers.unknown import catch_all_router
from bot.telegram_bot.handlers.user import user_commands_router
from bot.telegram_bot.middlewares import (
    ActiveTeamTalkConnectionMiddleware,
    SubscriptionCheckMiddleware,
)
from bot.telegram_bot.types.bots import EventBot

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
        # self.dp will be provided by dishka
        self.dp: Dispatcher | None = None

    async def run(self) -> None:
        """Sets up and runs the main application event loops."""
        self.logger.info("Application starting...")

        # Create and set up dishka container
        container = make_async_container(AppProvider(), RequestProvider(), AiogramProvider())
        self.dp = await container.get(Dispatcher)
        self.dp.workflow_data["dishka_container"] = container

        # Register middlewares
        self.dp.update.middleware.register(SubscriptionCheckMiddleware())
        self.dp.update.middleware.register(ActiveTeamTalkConnectionMiddleware(default_server_key=None))
        self.dp.callback_query.middleware(CallbackAnswerMiddleware())

        # Include routers
        self.dp.include_router(user_commands_router)
        self.dp.include_router(admin_router)
        self.dp.include_router(callback_router)
        self.dp.include_router(catch_all_router)

        # Register startup handler to be executed when the bot starts
        self.dp.startup.register(on_startup)

        # Set up dishka for aiogram integration
        setup_dishka(container, router=self.dp, auto_inject=True)

        self.logger.info("Starting Telegram polling...")
        try:
            # Retrieve the EventBot instance directly from the container
            bot_instance = await container.get(EventBot)
            # Start polling with the retrieved bot instance
            await self.dp.start_polling(bot_instance)
        finally:
            self.logger.info("Closing dishka container.")
            await container.close()


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
