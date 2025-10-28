"""Application-level Dishka providers for dependency injection."""

from collections.abc import Callable
import gettext
from gettext import NullTranslations

from cachetools import LRUCache
from dishka import FromDishka, Provider, Scope, provide

from bot.command_bus.bus import CommandBus
from bot.config import Settings
from bot.core.languages import DOMAIN, LOCALE_DIR, LanguageInfo, discover_languages
from bot.event_bus.bus import EventBus
from bot.services.cache_service import CacheService


def create_translator_factory(
    translator_cache: dict[str, NullTranslations],
) -> Callable[[str | None], NullTranslations]:
    """Creates and returns a factory function for retrieving translators."""

    def get_translator(lang_code: str | None) -> NullTranslations:
        if not lang_code:
            return gettext.NullTranslations()
        if lang_code in translator_cache:
            return translator_cache[lang_code]
        translation: NullTranslations
        try:
            translation = gettext.translation(
                DOMAIN, localedir=str(LOCALE_DIR), languages=[lang_code]
            )
        except FileNotFoundError:
            translation = gettext.NullTranslations()
        translator_cache[lang_code] = translation
        return translation

    return get_translator


class AppProvider(Provider):
    """Provides application-scoped dependencies."""

    scope = Scope.APP

    def __init__(self, settings: Settings, config_path: str) -> None:
        """Initializes the provider with application settings."""
        super().__init__()
        self._settings = settings
        self._config_path = config_path

    @provide
    def get_config_path(self) -> str:
        """Provides the path to the application config file."""
        return self._config_path

    @provide
    def get_settings(self) -> Settings:
        """Provides application settings."""
        return self._settings

    @provide
    @staticmethod
    def get_translator_cache() -> dict[str, NullTranslations]:
        """Provides a cache for translator objects."""
        return {}

    @provide
    @staticmethod
    def get_available_languages() -> list[LanguageInfo]:
        """Provides a list of available languages."""
        return discover_languages()

    @provide(scope=Scope.APP)
    @staticmethod
    def get_translator_factory(
        translator_cache: dict[str, NullTranslations],
    ) -> Callable[[str | None], NullTranslations]:
        """Provides a factory for creating translators."""
        return create_translator_factory(translator_cache)

    @provide(provides=Callable[[str], NullTranslations], scope=Scope.APP)
    @staticmethod
    def get_str_translator_factory(
        translator_factory: FromDishka[Callable[[str | None], NullTranslations]],
    ) -> Callable[[str], NullTranslations]:
        """Provides a factory for creating translators that only accepts strings."""

        def factory(lang_code: str) -> NullTranslations:
            return translator_factory(lang_code)

        return factory

    @provide
    @staticmethod
    def get_event_bus() -> EventBus:
        """Provides the application-wide event bus."""
        return EventBus()

    @provide
    @staticmethod
    def get_command_bus() -> CommandBus:
        """Provides the application-wide command bus."""
        return CommandBus()

    @provide
    @staticmethod
    def get_cache_service(settings: FromDishka[Settings]) -> CacheService:
        """Provides the application-wide cache service."""
        return CacheService(
            user_settings_cache=LRUCache(
                maxsize=settings.operational_parameters.user_settings_cache_max_size
            ),
            admin_ids_cache=set(),
            subscribed_users_cache=set(),
        )
