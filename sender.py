import asyncio
import argparse
import traceback
import logging
from datetime import datetime

from typing import Dict, Optional, Any

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from bot.models import UserSettings
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlalchemy.orm import selectinload
from bot import models as db_models
from bot.constants import DB_MAIN_NAME


from aiogram import Bot, Dispatcher, html
from aiogram.types import ErrorEvent, Message as AiogramMessage
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

import pytalk


import gettext
from pathlib import Path

from bot.logging_setup import setup_logging
from bot.database import crud
from bot.core.languages import discover_languages, DEFAULT_LANGUAGE_CODE

LOCALE_DIR = Path("locales")
DOMAIN = "messages"

from bot.telegram_bot.commands import set_telegram_commands
from bot.telegram_bot.middlewares import (
    DbSessionMiddleware,
    UserSettingsMiddleware,
    SubscriptionCheckMiddleware,
    ApplicationMiddleware,
    ActiveTeamTalkConnectionMiddleware,
    TeamTalkConnectionCheckMiddleware
)

from bot.teamtalk_bot.connection import TeamTalkConnection
# TeamTalk logic is in TeamTalkEventHandler


logger = logging.getLogger(__name__)

class Application:
    def __init__(self, app_config_instance):
        self.app_config = app_config_instance
        self.logger = setup_logging()

        self.tg_bot_event: Bot = Bot(token=self.app_config.TG_EVENT_TOKEN)
        self.tg_bot_message: Optional[Bot] = None
        if self.app_config.TG_BOT_MESSAGE_TOKEN:
            self.tg_bot_message = Bot(token=self.app_config.TG_BOT_MESSAGE_TOKEN)
        else:
            self.logger.warning("TG_BOT_MESSAGE_TOKEN not set, message sending capabilities might be limited.")
            self.tg_bot_message = self.tg_bot_event # Fallback to event bot for messages if not specified

        self.dp: Dispatcher = Dispatcher()
        self.tt_bot: pytalk.TeamTalkBot = pytalk.TeamTalkBot(client_name=self.app_config.CLIENT_NAME)

        _ = db_models
        database_files = {DB_MAIN_NAME: self.app_config.DATABASE_FILE}
        async_engines = {
            db_name: create_async_engine(f"sqlite+aiosqlite:///{db_file}")
            for db_name, db_file in database_files.items()
        }
        self.session_factory: sessionmaker = sessionmaker(
            async_engines[DB_MAIN_NAME], expire_on_commit=False, class_=AsyncSession
        )

        self.connections: Dict[str, TeamTalkConnection] = {}
        self.subscribed_users_cache: set[int] = set()
        self.admin_ids_cache: set[int] = set()
        self.user_settings_cache: Dict[int, Any] = {}
        self.translator_cache: dict[str, gettext.GNUTranslations] = {}
        self.available_languages: list = []

        self.teamtalk_task: Optional[asyncio.Task] = None
        from bot.teamtalk_bot.event_handler import TeamTalkEventHandler
        self.tt_event_handler = TeamTalkEventHandler(self)


    # --- Language and Translator Methods ---
    def get_translator(self, language_code: Optional[str] = None) -> gettext.GNUTranslations:
        """
        Returns a translator object for the specified language code.
        Caches translators after first load.
        Falls back to DEFAULT_LANGUAGE_CODE if the requested language is not found
        or if the default language itself fails to load (in which case NullTranslations is used).
        """
        if language_code is None:
            language_code = self.app_config.DEFAULT_LANG

        if language_code in self.translator_cache:
            return self.translator_cache[language_code]

        try:
            translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=[language_code])
            self.translator_cache[language_code] = translation
            return translation
        except FileNotFoundError:
            default_lang_code = self.app_config.DEFAULT_LANG
            if language_code != default_lang_code:
                self.logger.warning(f"Language '{language_code}' not found. Falling back to default '{default_lang_code}'.")
                return self.get_translator(default_lang_code)
            else:
                self.logger.error(f"Default language '{default_lang_code}' not found. Using NullTranslations.")
                null_trans = gettext.NullTranslations()
                self.translator_cache[language_code] = null_trans
                return null_trans

    # --- User Settings and Cache ---
    async def load_user_settings_to_app_cache(self):
        """Loads all user settings from DB into the application's cache."""
        async with self.session_factory() as session:
            stmt = select(UserSettings)
            result = await session.exec(stmt)
            all_settings = result.all()
            for setting in all_settings:
                self.user_settings_cache[setting.telegram_id] = setting
            self.logger.info(f"Loaded {len(self.user_settings_cache)} user settings into app cache.")

    async def get_or_create_user_settings(self, telegram_id: int, session: AsyncSession) -> UserSettings:
        """Gets user settings from app cache or DB, creates if not exists."""
        cached_settings = self.user_settings_cache.get(telegram_id)
        if cached_settings:
            return cached_settings

        user_settings = await session.get(
            UserSettings,
            telegram_id,
            options=[selectinload(UserSettings.muted_users_list)]
        )
        if not user_settings:
            self.logger.info(f"No settings found for user {telegram_id}, creating new ones.")
            user_settings = UserSettings(
                telegram_id=telegram_id,
                language_code=self.app_config.DEFAULT_LANG
            )
            session.add(user_settings)
            try:
                await session.commit()
                await session.refresh(user_settings)
                self.logger.info(f"Successfully created and saved new settings for user {telegram_id}.")
            except SQLAlchemyError as e:
                await session.rollback()
                self.logger.error(f"Database error creating settings for user {telegram_id}: {e}", exc_info=True)
                # Return a default non-persistent object on error.
                return UserSettings(telegram_id=telegram_id, language_code=self.app_config.DEFAULT_LANG)

        self.user_settings_cache[telegram_id] = user_settings
        return user_settings


    # --- Application Lifecycle Methods ---
    async def _on_startup_logic(self, bot: Bot, dispatcher: Dispatcher):
        """Internal logic for startup."""
        self.logger.info("Application startup: Initializing TeamTalk components...")

        if self.teamtalk_task is None or self.teamtalk_task.done():
            await self.tt_bot._async_setup_hook()
            self.teamtalk_task = asyncio.create_task(self.tt_bot._start(), name="teamtalk_bot_task_dispatcher")
            self.logger.info("Pytalk main event loop task started.")
        else:
            self.logger.info("Pytalk main event loop task already running.")

        async with self.session_factory() as session:
            db_admin_ids = await crud.get_all_admins_ids(session)
            self.admin_ids_cache.update(db_admin_ids)

            db_subscriber_ids = await crud.get_all_subscribers_ids(session)
            self.subscribed_users_cache.update(db_subscriber_ids)
        self.logger.info(f"Admin IDs cache populated from DB with {len(self.admin_ids_cache)} IDs.")
        self.logger.debug(f"Admin IDs cache populated from DB: {self.admin_ids_cache}")
        self.logger.info(f"Subscribed users cache populated with {len(self.subscribed_users_cache)} IDs.")

        await self.load_user_settings_to_app_cache()

        try:
            tg_admin_chat_id_str = self.app_config.TG_ADMIN_CHAT_ID
            if tg_admin_chat_id_str is not None:
                tg_admin_chat_id = int(tg_admin_chat_id_str)
                if tg_admin_chat_id not in self.admin_ids_cache:
                    async with self.session_factory() as session:
                        await crud.add_admin(session, tg_admin_chat_id)
                        self.admin_ids_cache.add(tg_admin_chat_id)
                    self.logger.debug(f"Main admin ID {tg_admin_chat_id} from config has been added to DB and cache.")
                else:
                    self.logger.debug(f"Main admin ID {tg_admin_chat_id} from config was already in admin cache.")
            else:
                self.logger.info("TG_ADMIN_CHAT_ID is not set in config, no main admin to add.")
        except (ValueError, TypeError) as e:
            self.logger.error(f"Could not process TG_ADMIN_CHAT_ID from config. It must be a valid integer. Error: {e}")

        self.logger.info(f"Final admin_ids_cache count after startup: {len(self.admin_ids_cache)}.")
        self.logger.debug(f"Final admin_ids_cache state after startup: {self.admin_ids_cache}")

        await set_telegram_commands(app=self)
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
        for conn_key, connection in self.connections.items():
            self.logger.info(f"Shutting down connection for {conn_key}...")
            await connection.disconnect_instance()
        self.logger.info("All TeamTalk connections processed for shutdown.")


        if hasattr(self.tg_bot_event, 'session') and self.tg_bot_event.session:
            await self.tg_bot_event.session.close()
        if self.tg_bot_message and hasattr(self.tg_bot_message, 'session') and self.tg_bot_message.session and self.tg_bot_message is not self.tg_bot_event:
            await self.tg_bot_message.session.close()
        self.logger.info("Telegram bot sessions closed.")
        self.logger.info("Application shutdown sequence complete.")

    async def _global_error_handler(self, event: ErrorEvent, bot: Bot):
        """Global error handler for uncaught exceptions in Aiogram handlers."""
        escaped_exception_text = html.quote(str(event.exception))
        self.logger.critical(f"Unhandled exception in Aiogram handler: {event.exception}", exc_info=True)

        if self.app_config.TG_ADMIN_CHAT_ID:
            try:
                admin_critical_translator = self.get_translator('ru')
                # Вся структура сообщения теперь одна переводимая строка
                error_text = admin_critical_translator.gettext(
                    "<b>Critical error!</b>\n"
                    "<b>Error type:</b> {error_type}\n"
                    "<b>Message:</b> {error_message}"
                ).format(
                    error_type=type(event.exception).__name__,
                    error_message=escaped_exception_text
                )
                await self.tg_bot_event.send_message(self.app_config.TG_ADMIN_CHAT_ID, error_text, parse_mode="HTML")
            except Exception as e:
                self.logger.error(f"Error sending critical error message to admin chat: {e}", exc_info=True)

        update = event.update
        user_id = None
        if update.message and update.message.from_user: user_id = update.message.from_user.id
        elif update.callback_query and update.callback_query.from_user: user_id = update.callback_query.from_user.id

        lang_code = DEFAULT_LANGUAGE_CODE
        if user_id:
            user_settings = self.user_settings_cache.get(user_id)
            if user_settings and user_settings.language_code:
                lang_code = user_settings.language_code

        translator = self.get_translator(lang_code)
        user_message_key = "An unexpected error occurred. The administrator has been notified. Please try again later."
        user_message_text = translator.gettext(user_message_key)

        if not (user_id and self.app_config.TG_ADMIN_CHAT_ID and str(user_id) == str(self.app_config.TG_ADMIN_CHAT_ID)):
            try:
                if update.message:
                    await update.message.answer(user_message_text)
                elif update.callback_query and isinstance(update.callback_query.message, AiogramMessage):
                    await update.callback_query.message.answer(user_message_text)
                elif user_id: # Try direct send if no reply context
                     await self.tg_bot_event.send_message(chat_id=user_id, text=user_message_text)
            except Exception as e:
                self.logger.error(f"Error sending error message to user {user_id if user_id else 'Unknown'}: {e}", exc_info=True)


    async def run(self):
        """Sets up and runs the application."""
        self.logger.info("Application starting...")

        self.logger.info("Discovering available languages...")
        self.available_languages = discover_languages()
        if not self.available_languages:
            self.logger.critical("No languages discovered. Check locales setup.")
            return
        else:
            self.logger.info(f"Available languages loaded: {[lang['code'] for lang in self.available_languages]}")

        # Import here to avoid circularity at module level
        from bot.telegram_bot.setup import setup_telegram_dispatcher
        setup_telegram_dispatcher(self)

        self.logger.info("Starting Telegram polling...")
        try:
            await self.dp.start_polling(self.tg_bot_event, allowed_updates=self.dp.resolve_used_update_types(), app=self)
        finally:
            self.logger.info("Application finished.")


# === CONFIGURATION AND CLI BLOCK START ===
def main_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default=".env",
        help="Path to the configuration file (e.g., .env, prod.env). Defaults to '.env'",
    )
    args, _ = parser.parse_known_args()

    from bot.config import Settings

    try:
        app_config_instance = Settings(_env_file=args.config)

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
