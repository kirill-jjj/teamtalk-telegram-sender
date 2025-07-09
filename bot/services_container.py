"""Provides a container for managing application-wide services and dependencies."""

import gettext
from gettext import GNUTranslations, NullTranslations
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import pytalk
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.config import Settings
from bot.core.languages import LanguageInfo, discover_languages
from bot.database.engine import AsyncSessionFactoryType
from bot.models import UserSettings
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.connection import TeamTalkConnection

if TYPE_CHECKING:
    pass  # Forward reference for selectinload, though might not be needed with plugin


# These might be passed to __init__ or defined globally if they are static
LOCALE_DIR = Path("locales")
DOMAIN = "messages"

logger = logging.getLogger(__name__)


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
        self.user_settings_cache: dict[int, UserSettings] = {}  # Changed Any to UserSettings

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
            return self.translator_cache[language_code]

        try:
            translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=[language_code])
            self.translator_cache[language_code] = translation
        except FileNotFoundError:
            default_lang_code = self.config.general.default_lang
            if language_code != default_lang_code:
                self.logger.warning(
                    "Language '%s' not found. Falling back to default '%s'.", language_code, default_lang_code
                )
                return self.get_translator(default_lang_code)  # Recursive call
            # This error is within an exception handler (FileNotFoundError), so use .exception
            self.logger.exception("Default language '%s' not found. Using NullTranslations.", default_lang_code)
            null_trans = gettext.NullTranslations()
            self.translator_cache[language_code] = null_trans  # Cache even null translation
            return null_trans

    async def load_user_settings_to_app_cache(self) -> None:
        """Loads all user settings from DB into the service's cache."""
        async with self.session_factory() as session:
            stmt = select(UserSettings).options(selectinload(UserSettings.muted_users_list))  # type: ignore[arg-type]
            result = await session.exec(stmt)
            all_settings = result.all()
            self.cache.load_all_user_settings(all_settings)
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
        self.available_languages = discover_languages(locales_path=str(LOCALE_DIR))
        if not self.available_languages:
            self.logger.critical("No languages discovered. Check locales setup.")
            # Decide error handling: raise, or operate with default only
        else:
            self.logger.info(
                "Available languages loaded into services: %s", [lang["code"] for lang in self.available_languages]
            )
