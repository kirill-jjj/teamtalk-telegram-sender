"""Dishka providers for dependency injection."""

from collections.abc import AsyncGenerator, Callable
import gettext
from gettext import NullTranslations
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
from bot.database.repositories.admin_repository import AdminRepository
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.models import UserSettings
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.moderation_service import ModerationService
from bot.services.report_service import ReportService
from bot.services.subscription_service import SubscriptionService
from bot.services.user_settings_service import UserSettingsService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.event_handler import TeamTalkEventHandler
from bot.telegram_bot.types.bots import EventBot, MessageBot


def create_translator_factory(
    translator_cache: dict[str, NullTranslations],
) -> Callable[[str], NullTranslations]:
    """Creates and returns a factory function for retrieving translators."""

    def get_translator(lang_code: str) -> NullTranslations:
        if lang_code in translator_cache:
            return translator_cache[lang_code]
        translation: NullTranslations
        try:
            translation = gettext.translation(DOMAIN, localedir=str(LOCALE_DIR), languages=[lang_code])
        except FileNotFoundError:
            translation = gettext.NullTranslations()
        translator_cache[lang_code] = translation
        return translation

    return get_translator


class AppProvider(Provider):
    """Provides application-scoped dependencies."""

    scope = Scope.APP

    def __init__(self, settings: Settings) -> None:
        """Initializes the provider with application settings."""
        super().__init__()
        self._settings = settings

    @provide
    def get_settings(self) -> Settings:
        """Provides application settings."""
        return self._settings

    @provide
    def get_session_factory(self, settings: Settings) -> AsyncSessionFactoryType:
        """Provides the database session factory."""
        return create_session_factory(settings)

    @provide(provides=EventBot)
    def get_bot_event(self, settings: Settings) -> EventBot:
        """Provides the event-handling Bot instance."""
        default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
        return cast(EventBot, Bot(token=settings.telegram.event_token, default=default_props))

    @provide(provides=MessageBot)
    def get_bot_message(self, settings: Settings) -> MessageBot:
        """Provides the message-sending Bot instance."""
        default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
        return cast(MessageBot, Bot(token=settings.telegram.message_token, default=default_props))

    @provide
    def get_dispatcher(self) -> Dispatcher:
        """Provides the aiogram Dispatcher."""
        return Dispatcher()

    @provide
    def get_teamtalk_bot(self, settings: Settings) -> pytalk.TeamTalkBot:
        """Provides the TeamTalk bot instance."""
        return pytalk.TeamTalkBot(client_name=settings.teamtalk.client_name)

    @provide
    def get_translator_cache(self) -> dict[str, NullTranslations]:
        """Provides a cache for translator objects."""
        return {}

    @provide
    def get_connections_dict(self) -> dict[str, TeamTalkConnection]:
        """Provides a dictionary for active TeamTalk connections."""
        return {}

    @provide
    def get_available_languages(self) -> list[LanguageInfo]:
        """Provides a list of available languages."""
        return discover_languages()

    @provide
    def get_translator_factory(
        self, translator_cache: dict[str, NullTranslations]
    ) -> Callable[[str], NullTranslations]:
        """Provides a factory for creating translators."""
        return create_translator_factory(translator_cache)

    @provide
    def get_cache_service(self) -> CacheService:
        """Provides the application-wide cache service."""
        return CacheService(user_settings_cache={}, admin_ids_cache=set(), subscribed_users_cache=set())

    @provide
    def get_teamtalk_event_handler(
        self,
        settings: FromDishka[Settings],
        session_factory: FromDishka[AsyncSessionFactoryType],
        cache: FromDishka[CacheService],
        translator_factory: FromDishka[Callable[[str], NullTranslations]],
        event_bot: FromDishka[EventBot],
        message_bot: FromDishka[MessageBot],
        tt_bot: FromDishka[pytalk.TeamTalkBot],
        connections: FromDishka[dict[str, TeamTalkConnection]],
    ) -> "TeamTalkEventHandler":
        """Provides the TeamTalk event handler."""
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


class RequestProvider(Provider):
    """Provides request-scoped dependencies."""

    scope = Scope.REQUEST

    @provide
    async def get_db_session(self, factory: AsyncSessionFactoryType) -> AsyncGenerator[AsyncSession, None]:
        """Provides a transaction-managed database session."""
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @provide
    def get_user_repository(self, session: AsyncSession) -> UserRepository:
        """Provides a UserRepository."""
        return UserRepository(session)

    @provide
    def get_ban_repository(self, session: AsyncSession) -> BanRepository:
        """Provides a BanRepository."""
        return BanRepository(session)

    @provide
    def get_deeplink_repository(self, session: AsyncSession) -> DeeplinkRepository:
        """Provides a DeeplinkRepository."""
        return DeeplinkRepository(session)

    @provide
    def get_admin_repository(self, session: AsyncSession) -> AdminRepository:
        """Provides an AdminRepository."""
        return AdminRepository(session)

    @provide
    def get_subscriber_repository(self, session: AsyncSession) -> SubscriberRepository:
        """Provides a SubscriberRepository."""
        return SubscriberRepository(session)

    @provide
    def get_deeplink_service(
        self,
        subscription_service: SubscriptionService,
        ban_repo: BanRepository,
        admin_repo: AdminRepository,
        cache: CacheService,
    ) -> DeeplinkService:
        """Provides a DeeplinkService."""
        return DeeplinkService(subscription_service, ban_repo, admin_repo, cache)

    @provide
    def get_user_settings_service(self, user_repo: UserRepository, cache: CacheService) -> UserSettingsService:
        """Provides a UserSettingsService."""
        return UserSettingsService(user_repo, cache)

    @provide
    def get_subscription_service(
        self,
        user_repo: UserRepository,
        subscriber_repo: SubscriberRepository,
        ban_repo: BanRepository,
        cache: CacheService,
    ) -> SubscriptionService:
        """Provides a SubscriptionService."""
        return SubscriptionService(user_repo, subscriber_repo, ban_repo, cache)

    @provide
    def get_moderation_service(
        self,
        ban_repo: BanRepository,
        user_repo: UserRepository,
        subscription_service: SubscriptionService,
        cache: CacheService,
    ) -> ModerationService:
        """Provides a ModerationService."""
        return ModerationService(ban_repo, user_repo, subscription_service, cache)

    @provide
    def get_report_service(self) -> ReportService:
        """Provides a ReportService."""
        return ReportService()

    @provide
    def get_user_from_event(self, event: TelegramObject) -> User | None:
        """Extracts the User object from the incoming event, if it exists.

        AiogramProvider provides the `event: TelegramObject`.
        This provider makes the `User` available for other dependencies.
        """
        return getattr(event, "from_user", None)

    @provide(provides=UserSettings | None)
    async def get_user_settings_optional(
        self,
        user: User | None,
        user_settings_service: UserSettingsService,
        settings: Settings,
    ) -> UserSettings | None:
        """Provides UserSettings if a user is present in the event."""
        if not user:
            return None
        return await user_settings_service.get_or_create(user.id, settings.general.default_lang)

    @provide
    def get_user_settings_guaranteed(
        self,
        user_settings: UserSettings | None,
    ) -> UserSettings:
        """Provides a guaranteed UserSettings object.

        Raises:
            ValueError: If UserSettings cannot be provided because no user
                        is present in the event context.
        """
        if user_settings is None:
            raise ValueError
        return user_settings

    @provide(provides=NullTranslations)
    def get_translator(
        self,
        user_settings: UserSettings | None,
        settings: Settings,
        translator_factory: Callable[[str], NullTranslations],
    ) -> NullTranslations:
        """Provides a translator for the current user's language."""
        lang_code = user_settings.language_code if user_settings else settings.general.default_lang
        return translator_factory(lang_code)

    @provide(provides=TeamTalkConnection | None)
    def get_tt_connection(self, connections: FromDishka[dict[str, TeamTalkConnection]]) -> TeamTalkConnection | None:
        """Provides the active TeamTalk connection."""
        if not connections:
            return None
        return next(iter(connections.values()), None)
