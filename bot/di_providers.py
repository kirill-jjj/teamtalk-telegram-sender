"""Dishka providers for dependency injection."""

# bot/di_providers.py

from collections.abc import AsyncGenerator, Callable
import gettext
from gettext import GNUTranslations, NullTranslations

from aiogram.types import TelegramObject, User
from dishka import Provider, Scope, provide
import pytalk
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.core.languages import DOMAIN, LOCALE_DIR, LanguageInfo, discover_languages
from bot.database.engine import AsyncSessionFactoryType, create_session_factory
from bot.models import UserSettings
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.connection import TeamTalkConnection


# 1. Выносим логику создания фабрики в отдельную функцию
def create_translator_factory(
    translator_cache: dict[str, GNUTranslations | NullTranslations],
) -> Callable[[str], GNUTranslations | NullTranslations]:
    """Создает и возвращает функцию-фабрику для получения переводчиков."""

    def get_translator(lang_code: str) -> GNUTranslations | NullTranslations:
        if lang_code in translator_cache:
            return translator_cache[lang_code]

        translation: GNUTranslations | NullTranslations
        try:
            translation = gettext.translation(DOMAIN, localedir=str(LOCALE_DIR), languages=[lang_code])
        except FileNotFoundError:
            # Возвращаем NullTranslations, если перевод не найден
            translation = gettext.NullTranslations()

        translator_cache[lang_code] = translation
        return translation

    return get_translator


class AppProvider(Provider):
    """Provides application-scoped dependencies."""

    scope = Scope.APP

    @provide
    def get_settings(self) -> Settings:
        """Загружает конфигурацию один раз при старте."""
        return Settings.from_toml("config.toml")

    @provide
    def get_session_factory(self, settings: Settings) -> AsyncSessionFactoryType:
        """Создает фабрику сессий, зависит от конфига."""
        return create_session_factory(settings)

    # Провайдеры для кэшей
    @provide
    def get_user_settings_cache(self) -> dict[int, UserSettings]:
        """Provides a cache for user settings."""
        return {}

    @provide
    def get_teamtalk_bot(self, settings: Settings) -> pytalk.TeamTalkBot:
        """Provides the TeamTalk bot instance."""
        return pytalk.TeamTalkBot(client_name=settings.teamtalk.client_name)

    @provide
    def get_admin_ids_cache(self) -> set[int]:
        """Provides a cache for admin IDs."""
        return set()

    @provide
    def get_subscribed_users_cache(self) -> set[int]:
        """Provides a cache for subscribed user IDs."""
        return set()

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

    # Провайдер для CacheService, который зависит от кэшей
    @provide
    def get_cache_service(
        self,
        user_settings_cache: dict[int, UserSettings],
        admin_ids_cache: set[int],
        subscribed_users_cache: set[int],
    ) -> CacheService:
        """Provides the cache service."""
        return CacheService(
            user_settings_cache=user_settings_cache,
            admin_ids_cache=admin_ids_cache,
            subscribed_users_cache=subscribed_users_cache,
        )


# --- Провайдер для компонентов, живущих в рамках одного запроса (Scope.REQUEST) ---


class RequestProvider(Provider):
    """Provides request-scoped dependencies."""

    scope = Scope.REQUEST

    @provide
    async def get_db_session(self, factory: AsyncSessionFactoryType) -> AsyncGenerator[AsyncSession, None]:
        """Создает сессию БД для каждого входящего update."""
        async with factory() as session:
            yield session

    @provide
    def get_event_user(self, event: TelegramObject) -> User | None:
        """Извлекает пользователя из события."""
        return getattr(event, "from_user", None)

    @provide
    async def get_user_settings(
        self,
        user: User | None,
        session: AsyncSession,
        settings: Settings,
        cache: CacheService,
    ) -> UserSettings | None:
        """Заменяет UserSettingsMiddleware. Создает или получает настройки пользователя."""
        if not user:
            return None

        user_settings = cache.get_user_settings(user.id)
        if user_settings:
            return user_settings

        # Логика из get_or_create_user_settings
        user_settings = await session.get(UserSettings, user.id)
        if not user_settings:
            user_settings = UserSettings(telegram_id=user.id, language_code=settings.general.default_lang)
            session.add(user_settings)
            await session.commit()
            await session.refresh(user_settings)  # Обновляем, чтобы подгрузить все поля

        cache.update_user_settings(user_settings)
        return user_settings

    @provide
    def get_translator(
        self,
        user_settings: UserSettings | None,
        settings: Settings,
        translator_cache: dict[str, GNUTranslations | NullTranslations],
    ) -> GNUTranslations | NullTranslations:
        """Заменяет I18nMiddleware. Предоставляет объект переводчика."""
        lang_code = user_settings.language_code if user_settings else settings.general.default_lang
        factory = create_translator_factory(translator_cache)
        return factory(lang_code)
