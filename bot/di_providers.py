"""Dishka providers for dependency injection."""

# bot/di_providers.py

import asyncio
from collections.abc import AsyncGenerator, Callable
import gettext
from gettext import GNUTranslations, NullTranslations
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject, Update, User
from dishka import Provider, Scope, provide
import pytalk
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from bot.config import Settings
from bot.core.languages import DOMAIN, LOCALE_DIR, LanguageInfo, discover_languages
from bot.database import crud
from bot.database.engine import AsyncSessionFactoryType, create_session_factory
from bot.models import UserSettings
from bot.services import admin_service
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.event_handler import TeamTalkEventHandler
from bot.telegram_bot.commands import set_telegram_commands as set_telegram_commands_for_bot


# 1. Выносим логику создания фабрики в отдельную функцию
def create_translator_factory(
    translator_cache: dict[str, GNUTranslations | NullTranslations]
) -> Callable[[str], GNUTranslations | NullTranslations]:
    """Создает и возвращает функцию-фабрику для получения переводчиков."""

    def get_translator(lang_code: str) -> GNUTranslations | NullTranslations:
        if lang_code in translator_cache:
            return translator_cache[lang_code]

        translation: GNUTranslations | NullTranslations
        try:
            translation = gettext.translation(
                DOMAIN, localedir=str(LOCALE_DIR), languages=[lang_code]
            )
        except FileNotFoundError:
            # Возвращаем NullTranslations, если перевод не найден
            translation = gettext.NullTranslations()

        translator_cache[lang_code] = translation
        return translation

    return get_translator


class AppProvider(Provider):
    """Provides application-scoped dependencies."""

    scope = Scope.APP

    dispatcher: Dispatcher

    @provide
    def get_dispatcher(self) -> Dispatcher:
        """Get the application's dispatcher."""
        return self.dispatcher

    @provide
    def get_settings(self) -> Settings:
        """Загружает конфигурацию один раз при старте."""
        return Settings.from_toml("config.toml")

    @provide
    def get_session_factory(self, settings: Settings) -> AsyncSessionFactoryType:
        """Создает фабрику сессий, зависит от конфига."""
        return create_session_factory(settings)

    @provide
    def get_bot_event(self, settings: Settings) -> Bot:
        """Создает основной экземпляр бота."""
        default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
        return Bot(token=settings.telegram.event_token, default=default_props)

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

    @provide(scope=Scope.APP)
    async def on_startup(
        self,
        dispatcher: Dispatcher,
        bot: Bot,
        tt_bot: pytalk.TeamTalkBot,
        cache: CacheService,
        session_factory: AsyncSessionFactoryType,
        settings: Settings,
        translator_factory: Callable[[str], GNUTranslations | NullTranslations],
        available_languages: list[LanguageInfo],
        connections: dict[str, TeamTalkConnection],
    ) -> None:
        """Application startup handler."""
        logger = logging.getLogger(__name__)
        logger.info("Application startup...")

        logger.info("Initializing TeamTalk components...")
        TeamTalkEventHandler(
            settings=settings,
            session_factory=session_factory,
            cache=cache,
            translator_factory=translator_factory,
            bot=bot,
            tt_bot=tt_bot,
            connections=connections,
            logger=logger,
        )
        teamtalk_task = dispatcher.workflow_data.get("teamtalk_task")
        if teamtalk_task is None or teamtalk_task.done():
            await tt_bot._async_setup_hook()
            task_name = "teamtalk_bot_task_dispatcher"
            teamtalk_task = asyncio.create_task(tt_bot._start(), name=task_name)
            dispatcher.workflow_data["teamtalk_task"] = teamtalk_task
            logger.info("Pytalk main event loop task started as '%s'.", task_name)
        else:
            logger.info("Pytalk main event loop task is already running.")

        logger.info("Loading all caches from database...")
        async with session_factory() as session:
            db_admin_ids = await crud.get_all_admins_ids(session)
            cache.load_admins_from_db(db_admin_ids)
            db_subscriber_ids = await crud.get_all_subscribers_ids(session)
            cache.load_subscribers_from_db(db_subscriber_ids)
            all_settings_result = await session.execute(
                select(UserSettings).options(
                    selectinload(UserSettings.muted_users_list)  # type: ignore[arg-type]
                )
            )
            cache.load_all_user_settings(list(all_settings_result.scalars().all()))
            logger.info("All caches have been loaded.")

            tg_admin_chat_id = settings.telegram.admin_chat_id
            if tg_admin_chat_id and not cache.is_admin(tg_admin_chat_id):
                logger.info("Configured admin %s not found in cache, ensuring presence.", tg_admin_chat_id)
                user_settings = await session.get(UserSettings, tg_admin_chat_id)
                if not user_settings:
                    user_settings = UserSettings(
                        telegram_id=tg_admin_chat_id,
                        language_code=settings.general.default_lang,
                    )
                    session.add(user_settings)
                    await session.commit()
                    await session.refresh(user_settings)
                translator = translator_factory(user_settings.language_code)
                await admin_service.add_admin(session, tg_admin_chat_id, user_settings, cache, bot, translator)

        logger.info("Setting Telegram bot commands...")
        await set_telegram_commands_for_bot(bot, cache, translator_factory, available_languages, settings)
        logger.info("Telegram bot commands set.")

        logger.info("Final admin count after startup: %s", cache.get_admin_count())
        logger.info("Application startup sequence complete.")


# --- Провайдер для компонентов, живущих в рамках одного запроса (Scope.REQUEST) ---

class RequestProvider(Provider):
    """Provides request-scoped dependencies."""

    scope = Scope.REQUEST

    @provide
    async def get_db_session(
        self, factory: AsyncSessionFactoryType
    ) -> AsyncGenerator[AsyncSession, None]:
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
            await session.refresh(user_settings) # Обновляем, чтобы подгрузить все поля

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
