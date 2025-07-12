"""Provides a container for managing application-wide services and dependencies."""

import asyncio
import gettext
from gettext import GNUTranslations, NullTranslations
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import pytalk
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.config import Settings
from bot.core.languages import LanguageInfo, discover_languages
from bot.database import crud
from bot.database.engine import AsyncSessionFactoryType
from bot.models import UserSettings
from bot.services import admin_service
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.telegram_bot.commands import set_telegram_commands as set_telegram_commands_for_bot

if TYPE_CHECKING:
    pass  # Forward reference for selectinload, though might not be needed with plugin


# Define the project root directory (parent directory of 'bot', which is parent of 'services_container.py')
# Path(__file__).resolve() -> .../teamtalk-telegram-sender/bot/services_container.py
# .parent -> .../teamtalk-telegram-sender/bot/
# .parent -> .../teamtalk-telegram-sender/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Now LOCALE_DIR will always point to the correct 'locales' directory relative to the project root
LOCALE_DIR = _PROJECT_ROOT / "locales"
DOMAIN = "messages"

logger = logging.getLogger(__name__)

# Add a logger for gettext itself to see its internal messages (if any)
gettext_logger = logging.getLogger("gettext")
# Set the DEBUG level for gettext_logger to see maximum detailed information.
# In production, this can be reverted to WARNING or INFO.
gettext_logger.setLevel(logging.DEBUG)


class Services:
    """Container for all application dependencies and services."""

    def __init__(self, config: Settings, session_factory: AsyncSessionFactoryType) -> None:
        """Initializes the Services container.

        Args:
            config: The application settings instance.
            session_factory: The SQLModel session factory.
        """
        self.config = config
        self.session_factory: AsyncSessionFactoryType = session_factory

        self.logger = logger

        default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
        self.bot_event: Bot = Bot(token=config.telegram.event_token, default=default_props)
        if config.telegram.message_token:
            self.bot_message: Bot = Bot(token=config.telegram.message_token, default=default_props)
        else:
            self.bot_message = self.bot_event

        self.tt_bot: pytalk.TeamTalkBot = pytalk.TeamTalkBot(client_name=config.teamtalk.client_name)

        self.connections: dict[str, TeamTalkConnection] = {}
        self.subscribed_users_cache: set[int] = set()
        self.admin_ids_cache: set[int] = set()
        self.user_settings_cache: dict[int, UserSettings] = {}

        self.translator_cache: dict[str, GNUTranslations | NullTranslations] = {}
        self.available_languages: list[LanguageInfo] = []

        self.cache = CacheService(self)

    def get_translator(self, language_code: str | None = None) -> GNUTranslations | NullTranslations:
        """Returns a translator object for the specified language code.

        Caches translators after first load.
        Falls back to DEFAULT_LANGUAGE_CODE if the requested language is not found
        or if the default language itself fails to load (in which case NullTranslations is used).
        """
        if language_code is None:
            language_code = self.config.general.default_lang

        if language_code in self.translator_cache:
            self.logger.debug("Translator for '%s' found in cache.", language_code)
            return self.translator_cache[language_code]

        # Log the loading attempt, including the resolved path to the locales directory
        self.logger.info(
            "Attempting to load translator for language '%s' from directory '%s'.",
            language_code,
            LOCALE_DIR.resolve(),
        )
        try:
            # gettext.translation searches for messages.mo in localedir/language_code/LC_MESSAGES/
            translation = gettext.translation(DOMAIN, localedir=str(LOCALE_DIR), languages=[language_code])
            self.translator_cache[language_code] = translation
            self.logger.info(
                "Translator for lang '%s' loaded successfully. Type: %s",
                language_code,
                type(translation).__name__,
            )
        except FileNotFoundError:
            # Log if translation file is not found for the given language
            self.logger.warning(
                "Localization files (.mo) not found for language '%s' in directory '%s'. "
                "Checking default language '%s'.",
                language_code,
                LOCALE_DIR.resolve(),
                self.config.general.default_lang,
            )
            default_lang_code = self.config.general.default_lang
            if language_code != default_lang_code:
                # Recursive call to try loading the default language
                return self.get_translator(default_lang_code)
            # If we are already trying to load the default language and FileNotFoundError occurs
            self.logger.exception(
                "CRITICAL ERROR: Localization files for default language '%s' not found in '%s'. "
                "Using NullTranslations. Ensure Babel 'compile' was executed.",
                default_lang_code,
                LOCALE_DIR.resolve(),
            )
            null_trans = gettext.NullTranslations()
            self.translator_cache[language_code] = null_trans  # Cache NullTranslations as well
            return null_trans
        except Exception:
            # Catch any other unexpected errors during translator loading
            self.logger.exception(
                "UNEXPECTED ERROR loading translator for lang '%s' from '%s'. Using NullTranslations.",
                language_code,
                LOCALE_DIR.resolve(),
            )
            null_trans = gettext.NullTranslations()
            self.translator_cache[language_code] = null_trans
            return null_trans
        else:
            return translation

    async def load_user_settings_to_app_cache(self) -> None:
        """Loads all user settings from DB into the service's cache."""
        async with self.session_factory() as session:
            stmt = select(UserSettings).options(selectinload(UserSettings.muted_users_list))  # type: ignore[arg-type]
            result = await session.exec(stmt)
            all_settings = result.all()
            self.cache.load_all_user_settings(list(all_settings))
            # Logging is handled by cache_service.load_all_user_settings

    async def get_or_create_user_settings(self, telegram_id: int, session: AsyncSession) -> UserSettings:
        """Gets user settings from CacheService or DB, creates if not exists, updates cache."""
        cached_settings = self.cache.get_user_settings(telegram_id)
        if cached_settings:
            return cached_settings

        user_settings = await session.get(
            UserSettings,
            telegram_id,
            options=[selectinload(UserSettings.muted_users_list)],  # type: ignore[arg-type]
        )
        if not user_settings:
            self.logger.info("No settings found for user %s, creating new ones.", telegram_id)
            user_settings = UserSettings(
                telegram_id=telegram_id,
                language_code=self.config.general.default_lang,
            )
            session.add(user_settings)
            try:
                await session.commit()
                # Refresh all, including relationships
                await session.refresh(user_settings, attribute_names=["muted_users_list"])
                self.logger.info("Successfully created and saved new settings for user %s.", telegram_id)
            except SQLAlchemyError:
                await session.rollback()
                self.logger.exception("Database error creating settings for user %s.", telegram_id)
                # Return a default non-persistent object on error.
                return UserSettings(telegram_id=telegram_id, language_code=self.config.general.default_lang)

        self.cache.update_user_settings(user_settings)
        return user_settings

    def initialize_languages(self) -> None:
        """Discovers and caches available languages."""
        self.available_languages = discover_languages(locales_path=LOCALE_DIR)
        if not self.available_languages:
            self.logger.critical("No languages discovered. Check locales setup.")
            # Decide error handling: raise, or operate with default only
        else:
            self.logger.info(
                "Available languages loaded into services: %s", [lang["code"] for lang in self.available_languages]
            )

    async def init_teamtalk(self, dispatcher: Dispatcher) -> None:
        """Initializes and starts the TeamTalk bot main event loop."""
        self.logger.info("Initializing TeamTalk components...")
        teamtalk_task = dispatcher.workflow_data.get("teamtalk_task")
        if teamtalk_task is None or teamtalk_task.done():
            await self.tt_bot._async_setup_hook()
            task_name = "teamtalk_bot_task_dispatcher"
            teamtalk_task = asyncio.create_task(self.tt_bot._start(), name=task_name)
            dispatcher.workflow_data["teamtalk_task"] = teamtalk_task
            self.logger.info("Pytalk main event loop task started as '%s'.", task_name)
        else:
            self.logger.info("Pytalk main event loop task is already running.")

    async def load_all_caches(self) -> None:
        """Loads admins, subscribers, and user settings from DB into cache."""
        self.logger.info("Loading all caches from database...")
        async with self.session_factory() as session:
            # Load admins
            db_admin_ids = await crud.get_all_admins_ids(session)
            self.cache.load_admins_from_db(db_admin_ids)
            # Load subscribers
            db_subscriber_ids = await crud.get_all_subscribers_ids(session)
            self.cache.load_subscribers_from_db(db_subscriber_ids)
        # Load user settings
        await self.load_user_settings_to_app_cache()
        self.logger.info("All caches have been loaded.")

    async def ensure_main_admin(self) -> None:
        """Ensures the admin from config is present in the database and cache."""
        tg_admin_chat_id = self.config.telegram.admin_chat_id
        if not tg_admin_chat_id:
            self.logger.info("No main admin configured, skipping.")
            return

        if self.cache.is_admin(tg_admin_chat_id):
            self.logger.debug("Main admin %s already in cache.", tg_admin_chat_id)
            return

        self.logger.info("Configured admin %s not found in cache, ensuring presence.", tg_admin_chat_id)
        async with self.session_factory() as session:
            user_settings = await self.get_or_create_user_settings(tg_admin_chat_id, session)
            if not user_settings:
                self.logger.error("Failed to get/create settings for admin %s.", tg_admin_chat_id)
                return

            # Assuming admin_service.add_admin_full handles all logic including cache update
            added = await admin_service.add_admin_full(
                session=session,
                telegram_id=tg_admin_chat_id,
                user_settings=user_settings,
                services=self,
            )
            if added:
                self.logger.info("Main admin %s added successfully.", tg_admin_chat_id)
            else:
                self.logger.error("Failed to add main admin %s.", tg_admin_chat_id)

    async def set_telegram_commands(self) -> None:
        """Sets the bot commands in Telegram."""
        self.logger.info("Setting Telegram bot commands...")
        await set_telegram_commands_for_bot(services=self)
        self.logger.info("Telegram bot commands set.")
