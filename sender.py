"""Main application entry point for the TeamTalk Telegram Sender bot."""

import argparse
import asyncio
import logging
import traceback
from types import ModuleType

from aiogram import Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
import aiohttp
from dishka import make_async_container
from dishka.integrations.aiogram import (
    AiogramProvider,
    FromDishka,
    inject,
    setup_dishka,
)
from pydantic import ValidationError
from toml import TomlDecodeError

from bot.config import Settings
from bot.di.app import AppProvider
from bot.di.database import DatabaseProvider
from bot.di.services import ServicesProvider
from bot.di.teamtalk import RequestProvider, TeamTalkProvider
from bot.di.telegram import TelegramProvider
from bot.lifecycle import on_startup
from bot.logging_setup import setup_logging
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.handlers.admin import admin_router
from bot.telegram_bot.handlers.callbacks import callback_router
from bot.telegram_bot.handlers.errors import error_router
from bot.telegram_bot.handlers.unknown import catch_all_router
from bot.telegram_bot.handlers.user import user_commands_router
from bot.telegram_bot.types.bots import EventBot, MessageBot

uvloop: ModuleType | None = None
try:
    import uvloop as uvloop_module

    uvloop = uvloop_module
except ImportError:
    pass

logger = logging.getLogger(__name__)


@inject
async def on_shutdown(
    dispatcher: FromDishka[Dispatcher],
    tt_connection: FromDishka[TeamTalkConnection],
    event_bot: FromDishka[EventBot],
    message_bot: FromDishka[MessageBot],
) -> None:
    """Handles application shutdown."""
    logger.info("Application shutting down...")

    # Close aiogram Bot sessions
    try:
        await event_bot.session.close()
        logger.info("EventBot session closed.")
    except (asyncio.CancelledError, aiohttp.ClientError):
        logger.exception("Error closing EventBot session: %s")

    try:
        await message_bot.session.close()
        logger.info("MessageBot session closed.")
    except (asyncio.CancelledError, aiohttp.ClientError):
        logger.exception("Error closing MessageBot session: %s")

    if tt_connection:
        try:
            await tt_connection.disconnect_instance()
        except asyncio.CancelledError:
            logger.info("TeamTalk connection disconnect cancelled.")

    teamtalk_task = dispatcher.workflow_data.get("teamtalk_task")
    if teamtalk_task and not teamtalk_task.done():
        teamtalk_task.cancel()
        try:
            await teamtalk_task
        except asyncio.CancelledError:
            logger.info("TeamTalk event loop task cancelled.")


class Application:
    """Main application class that manages the bot's lifecycle and components."""

    def __init__(self, app_config_instance: Settings, config_path: str) -> None:
        """Initializes the Application.

        Args:
            app_config_instance: The loaded application settings.
            config_path: The path to the configuration file.
        """
        self.app_config = app_config_instance
        self.config_path = config_path
        self.logger = setup_logging()
        self.dp: Dispatcher | None = None

    async def run(self) -> None:
        """Sets up and runs the main application event loops."""
        self.logger.info("Application starting...")

        app_provider = AppProvider(
            settings=self.app_config, config_path=self.config_path
        )
        container = make_async_container(
            app_provider,
            DatabaseProvider(),
            ServicesProvider(),
            TelegramProvider(),
            TeamTalkProvider(),
            RequestProvider(),
            AiogramProvider(),
        )

        self.dp = await container.get(Dispatcher)
        self.dp.workflow_data["dishka_container"] = container

        self.dp.include_router(user_commands_router)
        self.dp.include_router(admin_router)
        self.dp.include_router(callback_router)
        self.dp.include_router(catch_all_router)
        self.dp.include_router(error_router)

        self.dp.callback_query.middleware(CallbackAnswerMiddleware())

        self.dp.startup.register(on_startup)
        self.dp.shutdown.register(on_shutdown)

        setup_dishka(container, router=self.dp, auto_inject=True)

        self.logger.debug("Starting Telegram polling...")
        try:
            bot_instance = await container.get(EventBot)
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

        app = Application(app_config_instance, config_path=args.config)
        asyncio.run(app.run())

    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped by user.")
    except (ValueError, KeyError) as config_error:
        print(f"CRITICAL: Configuration Error: {config_error}.")
        traceback.print_exc()
    except (
        FileNotFoundError,
        TomlDecodeError,
        ValidationError,
        RuntimeError,
        TelegramAPIError,
        TelegramNetworkError,
    ) as e:
        print(f"CRITICAL: An unexpected critical error occurred: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main_cli()
