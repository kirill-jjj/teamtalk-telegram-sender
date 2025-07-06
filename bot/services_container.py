import gettext
import logging
from pathlib import Path

from aiogram import Bot
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload, sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession  # For type hinting

from bot.config import Settings

# Assuming discover_languages and DEFAULT_LANGUAGE_CODE are correctly importable
from bot.core.languages import discover_languages
from bot.models import UserSettings
from bot.teamtalk_bot.connection import TeamTalkConnection  # Assuming this path is correct

# These might be passed to __init__ or defined globally if they are static
LOCALE_DIR = Path("locales")
DOMAIN = "messages"

logger = logging.getLogger(__name__)

class Services:
    """Контейнер для всех зависимостей и сервисов приложения."""
    def __init__(self, config: Settings, session_factory: sessionmaker):
        self.config = config
        self.session_factory: sessionmaker[AsyncSession] = session_factory # Added type hint

        self.logger = logger

        # Боты
        self.bot_event: Bot = Bot(token=config.telegram.event_token)
        if config.telegram.message_token:
            self.bot_message: Bot = Bot(token=config.telegram.message_token)
        else:
            self.bot_message: Bot = self.bot_event

        # TeamTalk Bot instance
        import pytalk  # Import pytalk here
        self.tt_bot: pytalk.TeamTalkBot = pytalk.TeamTalkBot(client_name=config.teamtalk.client_name)


        # Состояние (кеши)
        self.connections: dict[str, TeamTalkConnection] = {}
        self.subscribed_users_cache: set[int] = set()
        self.admin_ids_cache: set[int] = set()
        self.user_settings_cache: dict[int, UserSettings] = {} # Changed Any to UserSettings

        # Инструменты
        self.translator_cache: dict[str, gettext.GNUTranslations] = {}
        self.available_languages: list[dict[str, str]] = [] # More specific type hint


    def get_translator(self, language_code: str | None = None) -> gettext.GNUTranslations:
        """
        Returns a translator object for the specified language code.
        Caches translators after first load.
        Falls back to DEFAULT_LANGUAGE_CODE if the requested language is not found
        or if the default language itself fails to load (in which case NullTranslations is used).
        """
        if language_code is None:
            language_code = self.config.general.default_lang # Use self.config

        if language_code in self.translator_cache:
            return self.translator_cache[language_code]

        try:
            translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=[language_code])
            self.translator_cache[language_code] = translation
            return translation
        except FileNotFoundError:
            default_lang_code = self.config.general.default_lang # Use self.config
            if language_code != default_lang_code:
                self.logger.warning(
                    f"Language '{language_code}' not found. Falling back to default '{default_lang_code}'."
                )
                return self.get_translator(default_lang_code) # Recursive call
            else:
                self.logger.error(
                    f"Default language '{default_lang_code}' not found. Using NullTranslations."
                )
                null_trans = gettext.NullTranslations()
                self.translator_cache[language_code] = null_trans # Cache even null translation
                return null_trans

    async def load_user_settings_to_app_cache(self): # Renamed from load_user_settings_to_app_cache for clarity
        """Loads all user settings from DB into the service's cache."""
        async with self.session_factory() as session:
            # Ensure muted_users are loaded
            stmt = select(UserSettings).options(selectinload(UserSettings.muted_users_list))
            result = await session.exec(stmt)
            all_settings = result.all()
            for setting in all_settings:
                self.user_settings_cache[setting.telegram_id] = setting
            self.logger.info(f"Loaded {len(self.user_settings_cache)} user settings into services cache.")

    async def get_or_create_user_settings(self, telegram_id: int, session: AsyncSession) -> UserSettings:
        """Gets user settings from service cache or DB, creates if not exists."""
        cached_settings = self.user_settings_cache.get(telegram_id)
        if cached_settings:
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
                language_code=self.config.general.default_lang # Use self.config
            )
            session.add(user_settings)
            try:
                await session.commit()
                # Refresh all, including relationships
                await session.refresh(user_settings, attribute_names=['muted_users_list'])
                self.logger.info(f"Successfully created and saved new settings for user {telegram_id}.")
            except SQLAlchemyError as e:
                await session.rollback()
                self.logger.error(f"Database error creating settings for user {telegram_id}: {e}", exc_info=True)
                # Return a default non-persistent object on error.
                return UserSettings(telegram_id=telegram_id, language_code=self.config.general.default_lang)

        self.user_settings_cache[telegram_id] = user_settings
        return user_settings

    def initialize_languages(self):
        """Discovers and caches available languages."""
        self.available_languages = discover_languages(locales_path=LOCALE_DIR)
        if not self.available_languages:
            self.logger.critical("No languages discovered. Check locales setup.")
            # Decide error handling: raise, or operate with default only
        else:
            self.logger.info(
                f"Available languages loaded into services: "
                f"{[lang['code'] for lang in self.available_languages]}"
            )
