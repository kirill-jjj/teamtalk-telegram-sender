"""Main application entry point for the TeamTalk Telegram Sender bot."""

import argparse
import asyncio
import logging
import traceback
from types import ModuleType  # For uvloop typing

# Project specific imports should be after standard library and before uvloop logic generally,
# but ruff E402 wants them at the very top if they don't depend on conditional uvloop.
# Let's place them here, before uvloop, to satisfy E402.
from aiogram import Dispatcher, html
from aiogram.types import ErrorEvent
from aiogram.types import Message as AiogramMessage

from bot.config import Settings
from bot.core.languages import DEFAULT_LANGUAGE_CODE
from bot.database import crud
from bot.database.engine import create_session_factory
from bot.logging_setup import setup_logging
from bot.services_container import Services
from bot.teamtalk_bot.event_handler import TeamTalkEventHandler
from bot.telegram_bot.commands import set_telegram_commands
from bot.telegram_bot.setup import setup_telegram_dispatcher

uvloop: ModuleType | None = None
try:
    import uvloop as uvloop_module  # type: ignore
    uvloop = uvloop_module
except ImportError:
    pass # uvloop remains None

logger = logging.getLogger(__name__)


class Application:
    """Main application class orchestrating the bot's lifecycle and components."""

    def __init__(self, app_config_instance: Settings):
        """Initializes the Application.

        Args:
            app_config_instance: The loaded application settings.
        """
        self.app_config = app_config_instance  # Store config for app-level decisions if any
        self.logger = setup_logging()

        # 1. Create session_factory using the new function
        session_factory = create_session_factory(app_config_instance)

        # 2. Create services container
        self.services = Services(config=app_config_instance, session_factory=session_factory)

        # 3. Create components that depend on services or app config
        self.dp: Dispatcher = Dispatcher()

        # Moved import to top: from bot.teamtalk_bot.event_handler import TeamTalkEventHandler
        # TeamTalkEventHandler now takes only services
        self.tt_event_handler = TeamTalkEventHandler(self.services)

        self.teamtalk_task: asyncio.Task | None = None

    # --- Application Lifecycle Methods ---
    async def _on_startup_logic(self, dispatcher: Dispatcher):
        """Internal logic for startup."""
        self.logger.info("Application startup: Initializing TeamTalk components...")

        if self.teamtalk_task is None or self.teamtalk_task.done():
            # tt_bot is now in services
            await self.services.tt_bot._async_setup_hook()  # Pytalk's internal setup
            # tt_bot._start() is the main loop for pytalk
            self.teamtalk_task = asyncio.create_task(self.services.tt_bot._start(), name="teamtalk_bot_task_dispatcher")
            self.logger.info("Pytalk main event loop task started.")
        else:
            self.logger.info("Pytalk main event loop task already running.")

        # Access caches via self.services
        async with self.services.session_factory() as session:
            db_admin_ids = await crud.get_all_admins_ids(session)
            self.services.admin_ids_cache.update(db_admin_ids)

            db_subscriber_ids = await crud.get_all_subscribers_ids(session)
            self.services.subscribed_users_cache.update(db_subscriber_ids)
        self.logger.info("Admin IDs cache populated from DB with %s IDs.", len(self.services.admin_ids_cache))
        self.logger.debug("Admin IDs cache populated from DB: %s", self.services.admin_ids_cache)
        self.logger.info("Subscribed users cache populated with %s IDs.", len(self.services.subscribed_users_cache))

        await self.services.load_user_settings_to_app_cache()

        # Accessing admin_chat_id from the new nested structure
        # app_config.telegram.admin_chat_id is now an int, not Optional[str]
        # Assuming 0 is not a valid/used admin_chat_id if it means "not set",
        # or that it's always a valid ID if present.
        # The TOML example has `admin_chat_id = 0`. If 0 means "not set", this logic needs adjustment.
        # For now, assume if admin_chat_id is present (Pydantic ensures it's an int), it's a valid ID to use.
        tg_admin_chat_id = self.app_config.telegram.admin_chat_id
        if tg_admin_chat_id:  # Simple check if it's non-zero; adjust if 0 is a valid ID to be added.
            # If the field is non-optional in Pydantic, it will always be present.
            if tg_admin_chat_id not in self.services.admin_ids_cache:  # Use services cache
                async with self.services.session_factory() as session:
                    await crud.add_admin(session, tg_admin_chat_id)
                    self.services.admin_ids_cache.add(tg_admin_chat_id)  # Update services cache
                self.logger.debug("Main admin ID %s from config has been added to DB and cache.", tg_admin_chat_id)
            else:
                self.logger.debug("Main admin ID %s from config was already in admin cache.", tg_admin_chat_id)
        else:
            self.logger.info("telegram.admin_chat_id is 0 or not configured in a way to be added as main admin.")
        # Removed original try-except for ValueError/TypeError as Pydantic handles type validation.

        self.logger.info("Final admin_ids_cache count after startup: %s.", len(self.services.admin_ids_cache))
        self.logger.debug("Final admin_ids_cache state after startup: %s", self.services.admin_ids_cache)

        # set_telegram_commands now expects only services
        await set_telegram_commands(services=self.services)
        self.logger.info("Telegram bot commands set.")

    async def _on_shutdown_logic(self, dispatcher: Dispatcher):
        """Handles application shutdown logic.

        Cancels running tasks and closes connections.

        Args:
            dispatcher: The Aiogram Dispatcher instance.
        """
        self.logger.warning("Application shutting down...")

        if self.teamtalk_task and not self.teamtalk_task.done():
            self.logger.info("Cancelling Pytalk main event loop task...")
            self.teamtalk_task.cancel()
            try:
                await self.teamtalk_task
            except asyncio.CancelledError:
                self.logger.info("Pytalk main event loop task cancelled successfully.")
            except Exception as e:
                self.logger.exception("Error awaiting cancelled Pytalk task: %s", e)
        elif self.teamtalk_task:
            self.logger.info("Pytalk main event loop task was already done.")
        else:
            self.logger.info("No Pytalk main event loop task found to cancel.")

        self.logger.info("Disconnecting TeamTalk instances...")
        # Connections are now in self.services.connections
        for conn_key, connection in self.services.connections.items():
            self.logger.info("Shutting down connection for %s...", conn_key)
            await connection.disconnect_instance()
        self.logger.info("All TeamTalk connections processed for shutdown.")

        # Bot sessions are in self.services
        if hasattr(self.services.bot_event, "session") and self.services.bot_event.session:
            await self.services.bot_event.session.close()
        if (
            self.services.bot_message
            and hasattr(self.services.bot_message, "session")
            and self.services.bot_message.session
            and self.services.bot_message is not self.services.bot_event
        ):
            await self.services.bot_message.session.close()
        self.logger.info("Telegram bot sessions closed.")
        self.logger.info("Application shutdown sequence complete.")

    # _global_error_handler now receives the dispatcher, not bot. bot is self.services.bot_event
    async def _global_error_handler(self, event: ErrorEvent, dispatcher: Dispatcher):
        """Global error handler for uncaught exceptions in Aiogram handlers."""
        escaped_exception_text = html.quote(str(event.exception))
        self.logger.critical("Unhandled exception in Aiogram handler: %s", event.exception, exc_info=True)

        # Use self.services.get_translator and self.services.bot_event
        # Access admin_chat_id from the new nested structure
        admin_chat_id_for_error = self.app_config.telegram.admin_chat_id
        admin_lang_code = self.app_config.general.default_lang  # Default to general default_lang

        if admin_chat_id_for_error:  # Check if it's non-zero or configured
            # Try to get admin's specific language if available
            admin_user_settings = self.services.user_settings_cache.get(admin_chat_id_for_error)
            if admin_user_settings and admin_user_settings.language_code:
                admin_lang_code = admin_user_settings.language_code

            try:
                admin_critical_translator = self.services.get_translator(admin_lang_code)
                # Вся структура сообщения теперь одна переводимая строка
                error_text = admin_critical_translator.gettext(
                    "<b>Critical error!</b>\n<b>Error type:</b> {error_type}\n<b>Message:</b> {error_message}"
                ).format(error_type=type(event.exception).__name__, error_message=escaped_exception_text)
                await self.services.bot_event.send_message(admin_chat_id_for_error, error_text, parse_mode="HTML")
            except Exception as e:
                self.logger.exception(
                    "Error sending critical error message to admin chat %s: %s",
                    admin_chat_id_for_error,
                    e,
                )

        update = event.update
        user_id = None
        if update.message and update.message.from_user:
            user_id = update.message.from_user.id
        elif update.callback_query and update.callback_query.from_user:
            user_id = update.callback_query.from_user.id

        lang_code = DEFAULT_LANGUAGE_CODE  # Fallback
        if user_id:
            # Access user_settings_cache via self.services
            user_settings = self.services.user_settings_cache.get(user_id)
            if user_settings and user_settings.language_code:
                lang_code = user_settings.language_code

        translator = self.services.get_translator(lang_code)
        user_message_key = "An unexpected error occurred. The administrator has been notified. Please try again later."
        user_message_text = translator.gettext(user_message_key)

        # Compare user_id with the (potentially zero) admin_chat_id from config
        # admin_chat_id_for_error is already defined above
        if not (user_id and admin_chat_id_for_error and user_id == admin_chat_id_for_error):
            try:
                if update.message:
                    await update.message.answer(user_message_text)
                elif update.callback_query and isinstance(update.callback_query.message, AiogramMessage):
                    await update.callback_query.message.answer(user_message_text)
                elif user_id:  # Try direct send if no reply context
                    await self.services.bot_event.send_message(chat_id=user_id, text=user_message_text)
            except Exception as e:
                self.logger.exception(
                    "Error sending error message to user %s: %s", user_id if user_id else "Unknown", e
                )

    async def run(self):
        """Sets up and runs the main application event loops."""
        self.logger.info("Application starting...")

        self.logger.info("Initializing available languages in services...")
        self.services.initialize_languages()  # Moved from direct App responsibility

        # setup_telegram_dispatcher will be modified to accept services
        setup_telegram_dispatcher(dp=self.dp, services=self.services, app_callbacks=self)  # Pass app for callbacks

        self.logger.info("Starting Telegram polling...")
        try:
            # Poll with bot_event from services. Pass services or specific components to dispatcher/handlers.
            await self.dp.start_polling(
                self.services.bot_event,
                allowed_updates=self.dp.resolve_used_update_types(),
                # Removed app=self, dispatcher workflow_data will be used instead
            )
        finally:
            self.logger.info("Application finished.")


# === CONFIGURATION AND CLI BLOCK START ===
def main_cli():
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
