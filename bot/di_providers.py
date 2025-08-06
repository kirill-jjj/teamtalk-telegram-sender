"""Dishka providers for dependency injection."""

# bot/di_providers.py

from collections.abc import AsyncGenerator, Callable
import gettext
from gettext import GNUTranslations, NullTranslations
import logging
from typing import cast

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject, User
from dishka import FromDishka, Provider, Scope, provide
import pytalk
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.config import Settings
from bot.core.languages import DOMAIN, LOCALE_DIR, LanguageInfo, discover_languages
from bot.database.engine import AsyncSessionFactoryType, create_session_factory
from bot.models import UserSettings
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.event_handler import TeamTalkEventHandler
from bot.telegram_bot.types.bots import EventBot, MessageBot


# 1. Isolate the factory creation logic into a separate function
def create_translator_factory(
    translator_cache: dict[str, GNUTranslations | NullTranslations],
) -> Callable[[str], GNUTranslations | NullTranslations]:
    """Creates and returns a factory function for retrieving translators."""

    def get_translator(lang_code: str) -> GNUTranslations | NullTranslations:
        if lang_code in translator_cache:
            return translator_cache[lang_code]

        translation: GNUTranslations | NullTranslations
        try:
            translation = gettext.translation(DOMAIN, localedir=str(LOCALE_DIR), languages=[lang_code])
        except FileNotFoundError:
            # Return NullTranslations if a translation is not found
            translation = gettext.NullTranslations()

        translator_cache[lang_code] = translation
        return translation

    return get_translator


class AppProvider(Provider):
    """Provides application-scoped dependencies."""

    scope = Scope.APP

    @provide
    def get_settings(self) -> Settings:
        """Loads the configuration once on startup."""
        return Settings.from_toml("config.toml")

    @provide
    def get_session_factory(self, settings: Settings) -> AsyncSessionFactoryType:
        """Creates a session factory, depends on the config."""
        return create_session_factory(settings)

    @provide(provides=EventBot)
    def get_bot_event(self, settings: Settings) -> EventBot:
        """Creates the main Bot instance for handling events."""
        default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
        return cast(EventBot, Bot(token=settings.telegram.event_token, default=default_props))

    @provide(provides=MessageBot)
    def get_bot_message(self, settings: Settings) -> MessageBot:
        """Creates the Bot instance for sending messages to admin."""
        default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
        return cast(MessageBot, Bot(token=settings.telegram.message_token, default=default_props))

    @provide
    def get_dispatcher(self) -> Dispatcher:
        """Creates the main Dispatcher instance."""
        return Dispatcher()

    @provide
    def get_teamtalk_bot(self, settings: Settings) -> pytalk.TeamTalkBot:
        """Provides the TeamTalk bot instance."""
        return pytalk.TeamTalkBot(client_name=settings.teamtalk.client_name)

    @provide
    def get_translator_cache(self) -> dict[str, GNUTranslations | NullTranslations]:
        """Provides a cache for translators."""
        return {}

    @provide
    def get_connections_dict(self) -> dict[str, TeamTalkConnection]:
        """Provides a dictionary of TeamTalk connections."""
        return {}

    @provide
    def get_available_languages(self) -> list[LanguageInfo]:
        """Provides a list of available languages."""
        return discover_languages()

    @provide
    def get_translator_factory(
        self, translator_cache: dict[str, GNUTranslations | NullTranslations]
    ) -> Callable[[str], GNUTranslations | NullTranslations]:
        """Provides a factory for creating translators."""
        return create_translator_factory(translator_cache)

    @provide
    def get_cache_service(self) -> CacheService:
        """Provides the cache service."""
        return CacheService(
            user_settings_cache={},
            admin_ids_cache=set(),
            subscribed_users_cache=set(),
        )

    @provide
    def get_teamtalk_event_handler(
        self,
        settings: Settings,
        session_factory: AsyncSessionFactoryType,
        cache: CacheService,
        translator_factory: Callable[[str], GNUTranslations | NullTranslations],
        event_bot: EventBot,
        message_bot: MessageBot,
        tt_bot: pytalk.TeamTalkBot,
        connections: dict[str, TeamTalkConnection],
    ) -> "TeamTalkEventHandler":
        """Provides the TeamTalk event handler, which registers Pytalk callbacks."""
        # dishka will automatically pass all dependencies here
        return TeamTalkEventHandler(
            settings=settings,
            session_factory=session_factory,
            cache=cache,
            translator_factory=translator_factory,
            event_bot=event_bot,
            message_bot=message_bot,
            tt_bot=tt_bot,
            connections=connections,
            logger=logging.getLogger(TeamTalkEventHandler.__module__),
        )


# --- Provider for components living within a single request (Scope.REQUEST) ---


class RequestProvider(Provider):
    """Provides request-scoped dependencies."""

    scope = Scope.REQUEST

    @provide
    async def get_db_session(self, factory: AsyncSessionFactoryType) -> AsyncGenerator[AsyncSession, None]:
        """Creates a DB session for each incoming update."""
        async with factory() as session:
            yield session

    @provide
    def get_event_user(self, event: TelegramObject) -> User | None:
        """Extracts the user from the event."""
        return getattr(event, "from_user", None)

    @provide
    async def get_user_settings(
        self,
        user: User | None,
        session: AsyncSession,
        settings: Settings,
        cache: CacheService,
    ) -> UserSettings | None:
        """Replaces UserSettingsMiddleware. Creates or retrieves user settings."""
        if not user:
            return None

        user_settings = cache.get_user_settings(user.id)
        if user_settings:
            return user_settings

        # Logic from get_or_create_user_settings
        user_settings = await session.get(UserSettings, user.id)
        if not user_settings:
            user_settings = UserSettings(telegram_id=user.id, language_code=settings.general.default_lang)
            session.add(user_settings)
            await session.commit()
            await session.refresh(user_settings)  # Refresh to load all fields

        cache.update_user_settings(user_settings)
        return user_settings

    @provide(provides=NullTranslations)
    def get_translator(
        self,
        user_settings: UserSettings | None,
        settings: Settings,
        translator_cache: dict[str, GNUTranslations | NullTranslations],
    ) -> GNUTranslations | NullTranslations:
        """Replaces I18nMiddleware. Provides a translator object."""
        lang_code = user_settings.language_code if user_settings else settings.general.default_lang
        factory = create_translator_factory(translator_cache)
        return factory(lang_code)

    @provide(provides=TeamTalkConnection | None)
    def get_tt_connection(self, connections: FromDishka[dict[str, TeamTalkConnection]]) -> TeamTalkConnection | None:
        """Provides the active TeamTalk connection.

        Currently returns the first available connection.
        Returns None if no connections are active.
        """
        if not connections:
            return None
        # Return the first available connection
        return next(iter(connections.values()), None)
