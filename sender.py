"""Main application entry point for the TeamTalk Telegram Sender bot."""

import argparse
import asyncio
import logging
import traceback
from types import ModuleType  # For uvloop typing

from aiogram import Dispatcher

from bot.config import Settings
from bot.database.engine import create_session_factory
from bot.logging_setup import setup_logging
from bot.services_container import Services
from bot.teamtalk_bot.event_handler import TeamTalkEventHandler
from bot.telegram_bot.setup import create_telegram_dispatcher, setup_telegram_dispatcher

uvloop: ModuleType | None = None
try:
    import uvloop as uvloop_module  # type: ignore

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

        session_factory = create_session_factory(app_config_instance)
        self.services = Services(config=app_config_instance, session_factory=session_factory)
        self.dp: Dispatcher | None = None  # Will be initialized in run()
        self.tt_event_handler = TeamTalkEventHandler(self.services)
        # self.teamtalk_task is removed as it's now managed in setup.py via dispatcher.workflow_data

    async def run(self) -> None:
        """Sets up and runs the main application event loops."""
        self.logger.info("Application starting...")

        self.logger.info("Initializing available languages in services...")
        self.services.initialize_languages()

        self.dp = create_telegram_dispatcher()

        # Setup the dispatcher without app_callbacks
        setup_telegram_dispatcher(dp=self.dp, services=self.services)

        self.logger.info("Starting Telegram polling...")
        try:
            await self.dp.start_polling(
                self.services.bot_event,
                allowed_updates=self.dp.resolve_used_update_types(),
            )
        finally:
            self.logger.info("Application finished.")


# === CONFIGURATION AND CLI BLOCK START ===
def main_cli() -> None:
    """Main command-line interface function to start the bot.

    Parses arguments, loads configuration, sets up uvloop if available,
    and runs the application.
    """
    parser = argparse.ArgumentParser(description="TeamTalk Telegram Sender Bot")
    parser.add_argument(
        "--config",
        type=str,
        default="config.toml",  # Changed default to config.toml
        help="Path to the TOML configuration file (e.g., config.toml, config.prod.toml). Defaults to 'config.toml'",
    )
    args, _ = parser.parse_known_args()  # Keep known_args if other CLI tools might chain here, otherwise parse_args()

    try:
        print(f"Loading configuration from: {args.config}")
        app_config_instance = Settings.from_toml(args.config)

        try:
            if uvloop:  # Check if uvloop was successfully imported
                uvloop.install()
                print("uvloop installed and used.")
            else:
                print("uvloop not found (ImportError at top), using default asyncio event loop.")
        except Exception as e_uvloop:  # Catch potential errors during uvloop.install() itself
            print(f"Error during uvloop.install(): {e_uvloop}. Using default asyncio event loop.")

        app = Application(app_config_instance)
        asyncio.run(app.run())

    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped by user.")
    except (ValueError, KeyError) as config_error:
        print(f"CRITICAL: Configuration Error: {config_error}.")
        print("Please check your config.toml file or environment variables.")
        traceback.print_exc()
    except Exception as e:
        print(f"CRITICAL: An unexpected critical error occurred at CLI level: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main_cli()
