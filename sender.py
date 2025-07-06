import asyncio
import argparse
import traceback
import logging
# from datetime import datetime # No longer needed here

from typing import Optional

from bot.config import Settings # For type hinting app_config_instance
from bot.database.engine import create_session_factory

from aiogram import Dispatcher, html
from aiogram.types import ErrorEvent, Message as AiogramMessage # For _global_error_handler

import pytalk

from bot.logging_setup import setup_logging
from bot.database import crud # Used in _on_startup_logic
from bot.core.languages import DEFAULT_LANGUAGE_CODE # For _global_error_handler fallback

from bot.telegram_bot.commands import set_telegram_commands

# Import Services container
from bot.services_container import Services


logger = logging.getLogger(__name__)

class Application:
    def __init__(self, app_config_instance: Settings):
        self.app_config = app_config_instance # Store config for app-level decisions if any
        self.logger = setup_logging()

        # 1. Create session_factory using the new function
        session_factory = create_session_factory(app_config_instance)

        # 2. Create services container
        self.services = Services(config=app_config_instance, session_factory=session_factory)

        # 3. Create components that depend on services or app config
        self.dp: Dispatcher = Dispatcher()

        from bot.teamtalk_bot.event_handler import TeamTalkEventHandler
        # TeamTalkEventHandler now takes only services
        self.tt_event_handler = TeamTalkEventHandler(self.services)


        self.teamtalk_task: Optional[asyncio.Task] = None


    # --- Application Lifecycle Methods ---
    async def _on_startup_logic(self, dispatcher: Dispatcher):
        """Internal logic for startup."""
        self.logger.info("Application startup: Initializing TeamTalk components...")

        if self.teamtalk_task is None or self.teamtalk_task.done():
            # tt_bot is now in services
            await self.services.tt_bot._async_setup_hook() # Pytalk's internal setup
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
        self.logger.info(f"Admin IDs cache populated from DB with {len(self.services.admin_ids_cache)} IDs.")
        self.logger.debug(f"Admin IDs cache populated from DB: {self.services.admin_ids_cache}")
        self.logger.info(f"Subscribed users cache populated with {len(self.services.subscribed_users_cache)} IDs.")

        await self.services.load_user_settings_to_app_cache()

        try:
            tg_admin_chat_id_str = self.app_config.TG_ADMIN_CHAT_ID
            if tg_admin_chat_id_str is not None:
                tg_admin_chat_id = int(tg_admin_chat_id_str)
                if tg_admin_chat_id not in self.services.admin_ids_cache: # Use services cache
                    async with self.services.session_factory() as session:
                        await crud.add_admin(session, tg_admin_chat_id)
                        self.services.admin_ids_cache.add(tg_admin_chat_id) # Update services cache
                    self.logger.debug(f"Main admin ID {tg_admin_chat_id} from config has been added to DB and cache.")
                else:
                    self.logger.debug(f"Main admin ID {tg_admin_chat_id} from config was already in admin cache.")
            else:
                self.logger.info("TG_ADMIN_CHAT_ID is not set in config, no main admin to add.")
        except (ValueError, TypeError) as e:
            self.logger.error(f"Could not process TG_ADMIN_CHAT_ID from config. It must be a valid integer. Error: {e}")

        self.logger.info(f"Final admin_ids_cache count after startup: {len(self.services.admin_ids_cache)}.")
        self.logger.debug(f"Final admin_ids_cache state after startup: {self.services.admin_ids_cache}")

        # set_telegram_commands now expects only services
        await set_telegram_commands(services=self.services)
        self.logger.info("Telegram bot commands set.")


    async def _on_shutdown_logic(self, dispatcher: Dispatcher):
        """Internal logic for shutdown."""
        self.logger.warning('Application shutting down...')

        if self.teamtalk_task and not self.teamtalk_task.done():
            self.logger.info("Cancelling Pytalk main event loop task...")
            self.teamtalk_task.cancel()
            try:
                await self.teamtalk_task
            except asyncio.CancelledError:
                self.logger.info("Pytalk main event loop task cancelled successfully.")
            except Exception as e:
                self.logger.error(f"Error awaiting cancelled Pytalk task: {e}", exc_info=True)
        elif self.teamtalk_task:
            self.logger.info("Pytalk main event loop task was already done.")
        else:
            self.logger.info("No Pytalk main event loop task found to cancel.")

        self.logger.info("Disconnecting TeamTalk instances...")
        # Connections are now in self.services.connections
        for conn_key, connection in self.services.connections.items():
            self.logger.info(f"Shutting down connection for {conn_key}...")
            await connection.disconnect_instance()
        self.logger.info("All TeamTalk connections processed for shutdown.")

        # Bot sessions are in self.services
        if hasattr(self.services.bot_event, 'session') and self.services.bot_event.session:
            await self.services.bot_event.session.close()
        if self.services.bot_message and \
           hasattr(self.services.bot_message, 'session') and \
           self.services.bot_message.session and \
           self.services.bot_message is not self.services.bot_event:
            await self.services.bot_message.session.close()
        self.logger.info("Telegram bot sessions closed.")
        self.logger.info("Application shutdown sequence complete.")

    # _global_error_handler now receives the dispatcher, not bot. bot is self.services.bot_event
    async def _global_error_handler(self, event: ErrorEvent, dispatcher: Dispatcher):
        """Global error handler for uncaught exceptions in Aiogram handlers."""
        escaped_exception_text = html.quote(str(event.exception))
        self.logger.critical(f"Unhandled exception in Aiogram handler: {event.exception}", exc_info=True)

        # Use self.services.get_translator and self.services.bot_event
        if self.app_config.TG_ADMIN_CHAT_ID:
            try:
                admin_critical_translator = self.services.get_translator('ru')
                # Вся структура сообщения теперь одна переводимая строка
                error_text = admin_critical_translator.gettext(
                    "<b>Critical error!</b>\n"
                    "<b>Error type:</b> {error_type}\n"
                    "<b>Message:</b> {error_message}"
                ).format(
                    error_type=type(event.exception).__name__,
                    error_message=escaped_exception_text
                )
                await self.services.bot_event.send_message(self.app_config.TG_ADMIN_CHAT_ID, error_text, parse_mode="HTML")
            except Exception as e:
                self.logger.error(f"Error sending critical error message to admin chat: {e}", exc_info=True)

        update = event.update
        user_id = None
        if update.message and update.message.from_user: user_id = update.message.from_user.id
        elif update.callback_query and update.callback_query.from_user: user_id = update.callback_query.from_user.id

        lang_code = DEFAULT_LANGUAGE_CODE # Fallback
        if user_id:
            # Access user_settings_cache via self.services
            user_settings = self.services.user_settings_cache.get(user_id)
            if user_settings and user_settings.language_code:
                lang_code = user_settings.language_code

        translator = self.services.get_translator(lang_code)
        user_message_key = "An unexpected error occurred. The administrator has been notified. Please try again later."
        user_message_text = translator.gettext(user_message_key)

        if not (user_id and self.app_config.TG_ADMIN_CHAT_ID and str(user_id) == str(self.app_config.TG_ADMIN_CHAT_ID)):
            try:
                if update.message:
                    await update.message.answer(user_message_text)
                elif update.callback_query and isinstance(update.callback_query.message, AiogramMessage):
                    await update.callback_query.message.answer(user_message_text)
                elif user_id: # Try direct send if no reply context
                     await self.services.bot_event.send_message(chat_id=user_id, text=user_message_text)
            except Exception as e:
                self.logger.error(f"Error sending error message to user {user_id if user_id else 'Unknown'}: {e}", exc_info=True)


    async def run(self):
        """Sets up and runs the application."""
        self.logger.info("Application starting...")

        self.logger.info("Initializing available languages in services...")
        self.services.initialize_languages() # Moved from direct App responsibility

        # Import here to avoid circularity at module level
        from bot.telegram_bot.setup import setup_telegram_dispatcher
        # setup_telegram_dispatcher will be modified to accept services
        setup_telegram_dispatcher(dp=self.dp, services=self.services, app_callbacks=self) # Pass app for callbacks

        self.logger.info("Starting Telegram polling...")
        try:
            # Poll with bot_event from services. Pass services or specific components to dispatcher/handlers.
            await self.dp.start_polling(
                self.services.bot_event,
                allowed_updates=self.dp.resolve_used_update_types()
                # Removed app=self, dispatcher workflow_data will be used instead
            )
        finally:
            self.logger.info("Application finished.")


# === CONFIGURATION AND CLI BLOCK START ===
def main_cli():
    parser = argparse.ArgumentParser(description="TeamTalk Telegram Sender Bot")
    parser.add_argument(
        "--config",
        type=str,
        default="config.toml",  # Changed default to config.toml
        help="Path to the TOML configuration file (e.g., config.toml, config.prod.toml). Defaults to 'config.toml'",
    )
    args, _ = parser.parse_known_args() # Keep known_args if other CLI tools might chain here, otherwise parse_args()

    from bot.config import Settings # Keep for type hinting and access to from_toml

    try:
        print(f"Loading configuration from: {args.config}")
        app_config_instance = Settings.from_toml(args.config)

        try:
            import uvloop
            uvloop.install()
            print("uvloop installed and used.")
        except ImportError:
            print("uvloop not found, using default asyncio event loop.")

        app = Application(app_config_instance)
        asyncio.run(app.run())

    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped by user.")
    except (ValueError, KeyError) as config_error:
        print(f"CRITICAL: Configuration Error: {config_error}. Please check your .env file or environment variables.")
        traceback.print_exc()
    except Exception as e:
        print(f"CRITICAL: An unexpected critical error occurred at CLI level: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main_cli()
