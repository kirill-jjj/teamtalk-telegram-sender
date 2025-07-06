import gettext
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Set, List

from aiogram import Bot
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession # For type hinting
from sqlmodel import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError

from bot.config import Settings
from bot.models import UserSettings
from bot.teamtalk_bot.connection import TeamTalkConnection # Assuming this path is correct
# Assuming discover_languages and DEFAULT_LANGUAGE_CODE are correctly importable
from bot.core.languages import DEFAULT_LANGUAGE_CODE, discover_languages


# These might be passed to __init__ or defined globally if they are static
LOCALE_DIR = Path("locales")
DOMAIN = "messages"

logger = logging.getLogger(__name__)

class Services:
    """Контейнер для всех зависимостей и сервисов приложения."""
    def __init__(self, config: Settings, session_factory: sessionmaker):
        self.config = config
        self.session_factory: sessionmaker[AsyncSession] = session_factory # Added type hint

        # Logging - Assuming logger is configured elsewhere or passed if needed per service
        # For now, methods here will use the module-level logger
        self.logger = logger # Or pass a logger instance if preferred

        # Боты
        self.bot_event: Bot = Bot(token=config.TG_EVENT_TOKEN)
        self.bot_message: Bot = Bot(token=config.TG_BOT_MESSAGE_TOKEN) if config.TG_BOT_MESSAGE_TOKEN else self.bot_event

        # TeamTalk Bot instance
        import pytalk # Import pytalk here
        self.tt_bot: pytalk.TeamTalkBot = pytalk.TeamTalkBot(client_name=config.CLIENT_NAME)


        # Состояние (кеши)
        self.connections: Dict[str, TeamTalkConnection] = {}
        self.subscribed_users_cache: Set[int] = set()
        self.admin_ids_cache: Set[int] = set()
        self.user_settings_cache: Dict[int, UserSettings] = {} # Changed Any to UserSettings

        # Инструменты
        self.translator_cache: Dict[str, gettext.GNUTranslations] = {}
        self.available_languages: List[Dict[str, str]] = [] # More specific type hint


    def get_translator(self, language_code: Optional[str] = None) -> gettext.GNUTranslations:
        """
        Returns a translator object for the specified language code.
        Caches translators after first load.
        Falls back to DEFAULT_LANGUAGE_CODE if the requested language is not found
        or if the default language itself fails to load (in which case NullTranslations is used).
        """
        if language_code is None:
            language_code = self.config.DEFAULT_LANG # Use self.config

        if language_code in self.translator_cache:
            return self.translator_cache[language_code]

        try:
            translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=[language_code])
            self.translator_cache[language_code] = translation
            return translation
        except FileNotFoundError:
            default_lang_code = self.config.DEFAULT_LANG # Use self.config
            if language_code != default_lang_code:
                self.logger.warning(f"Language '{language_code}' not found. Falling back to default '{default_lang_code}'.")
                return self.get_translator(default_lang_code) # Recursive call
            else:
                self.logger.error(f"Default language '{default_lang_code}' not found. Using NullTranslations.")
                null_trans = gettext.NullTranslations()
                self.translator_cache[language_code] = null_trans # Cache even null translation
                return null_trans

    async def load_user_settings_to_app_cache(self): # Renamed from load_user_settings_to_app_cache for clarity
        """Loads all user settings from DB into the service's cache."""
        async with self.session_factory() as session:
            stmt = select(UserSettings).options(selectinload(UserSettings.muted_users_list)) # Ensure muted_users are loaded
            result = await session.exec(stmt)
            all_settings = result.all()
            for setting in all_settings:
                self.user_settings_cache[setting.telegram_id] = setting
            self.logger.info(f"Loaded {len(self.user_settings_cache)} user settings into services cache.")

    async def get_or_create_user_settings(self, telegram_id: int, session: AsyncSession) -> UserSettings:
        """Gets user settings from service cache or DB, creates if not exists."""
        cached_settings = self.user_settings_cache.get(telegram_id)
        if cached_settings:
            # To ensure the session is aware of the cached object if it's used for DB operations later
            # This can be tricky. If the object is modified and then used with a new session,
            # it might lead to issues. For read-only use from cache, it's fine.
            # If modifications are expected, re-fetching or merging might be safer.
            # For now, assume it's merged into the session or handled appropriately by the caller.
            # A simple way to ensure it's "live" for the given session (if needed for write):
            # if session.is_active:
            #    cached_settings = await session.merge(cached_settings)
            return cached_settings

        user_settings = await session.get(
            UserSettings,
            telegram_id,
            options=[selectinload(UserSettings.muted_users_list)] # Eager load related data
        )
        if not user_settings:
            self.logger.info(f"No settings found for user {telegram_id}, creating new ones.")
            user_settings = UserSettings(
                telegram_id=telegram_id,
                language_code=self.config.DEFAULT_LANG # Use self.config
            )
            session.add(user_settings)
            try:
                await session.commit()
                await session.refresh(user_settings, attribute_names=['muted_users_list']) # Refresh all, including relationships
                self.logger.info(f"Successfully created and saved new settings for user {telegram_id}.")
            except SQLAlchemyError as e:
                await session.rollback()
                self.logger.error(f"Database error creating settings for user {telegram_id}: {e}", exc_info=True)
                # Return a default non-persistent object on error.
                return UserSettings(telegram_id=telegram_id, language_code=self.config.DEFAULT_LANG)

        self.user_settings_cache[telegram_id] = user_settings
        return user_settings

    def initialize_languages(self):
        """Discovers and caches available languages."""
        self.available_languages = discover_languages(locales_path=LOCALE_DIR)
        if not self.available_languages:
            self.logger.critical("No languages discovered. Check locales setup.")
            # Decide error handling: raise, or operate with default only
        else:
            self.logger.info(f"Available languages loaded into services: {[lang['code'] for lang in self.available_languages]}")

    # Placeholder for other service methods that might be migrated or added
    # Example:
    # async def some_other_service_method(self, ...):
    #     # ... logic ...
    #     pass
