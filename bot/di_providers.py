"""Dishka providers for dependency injection."""

from collections.abc import Callable
import gettext
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING, cast

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject, User
from dishka import AsyncContainer, FromDishka, Provider, Scope, provide
import pytalk

from bot.config import Settings
from bot.core.exceptions import NoActiveTeamTalkConnectionError
from bot.core.languages import DOMAIN, LOCALE_DIR, LanguageInfo, discover_languages
from bot.database.engine import AsyncSessionFactoryType, create_session_factory
from bot.database.repositories.admin_repository import AdminRepository
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.database.uow import IUnitOfWork, SqlModelUnitOfWork
from bot.event_bus.bus import EventBus
from bot.event_handlers.teamtalk_replier import TeamTalkReplyHandler
from bot.event_handlers.telegram_notifier import TelegramNotificationHandler
from bot.models import UserSettings
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.moderation_service import ModerationService
from bot.services.notification_service import NotificationRecipientService
from bot.services.report_service import ReportService
from bot.services.subscription_service import SubscriptionService
from bot.services.user_settings_service import UserSettingsService
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter
from bot.telegram_bot.types.bots import EventBot, MessageBot

if TYPE_CHECKING:
    from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter


def create_translator_factory(
    translator_cache: dict[str, NullTranslations],
) -> Callable[[str], NullTranslations]:
    """Creates and returns a factory function for retrieving translators."""

    def get_translator(lang_code: str) -> NullTranslations:
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


def _create_bot(token: str) -> Bot:
    """Creates a Bot instance with default properties."""
    default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    return Bot(token=token, default=default_props)


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
        bot = _create_bot(token=settings.telegram.event_token)
        return cast(EventBot, bot)

    @provide(provides=MessageBot)
    def get_bot_message(self, settings: Settings) -> MessageBot:
        """Provides the message-sending Bot instance."""
        bot = _create_bot(token=settings.telegram.message_token)
        return cast(MessageBot, bot)

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
    def get_event_bus(self) -> EventBus:
        """Provides the application-wide event bus."""
        return EventBus()

    @provide
    def get_cache_service(self) -> CacheService:
        """Provides the application-wide cache service."""
        return CacheService(
            user_settings_cache={}, admin_ids_cache=set(), subscribed_users_cache=set()
        )

    @provide
    def get_pytalk_event_router(
        self,
        settings: FromDishka[Settings],
        dishka_container: FromDishka[AsyncContainer],
        cache: FromDishka[CacheService],
        translator_factory: FromDishka[Callable[[str], NullTranslations]],
        event_bus: FromDishka[EventBus],
        tt_bot: FromDishka[pytalk.TeamTalkBot],
        connections: FromDishka[dict[str, TeamTalkConnection]],
    ) -> "PytalkEventRouter":
        """Provides the Pytalk event router."""
        return PytalkEventRouter(
            settings=settings,
            dishka_container=dishka_container,
            cache=cache,
            translator_factory=translator_factory,
            event_bus=event_bus,
            tt_bot=tt_bot,
            connections=connections,
            logger=logging.getLogger(PytalkEventRouter.__module__),
        )

    @provide
    def get_notification_recipient_service(
        self,
        session_factory: FromDishka[AsyncSessionFactoryType],
        cache: FromDishka[CacheService],
    ) -> NotificationRecipientService:
        """Provides a NotificationRecipientService."""
        return NotificationRecipientService(session_factory, cache)

    @provide
    def get_telegram_notification_handler(
        self,
        event_bot: FromDishka[EventBot],
        message_bot: FromDishka[MessageBot],
        cache: FromDishka[CacheService],
        settings: FromDishka[Settings],
        translator_factory: FromDishka[Callable[[str], NullTranslations]],
        event_bus: FromDishka[EventBus],
        recipient_service: FromDishka[NotificationRecipientService],
    ) -> TelegramNotificationHandler:
        """Provides the Telegram notification handler."""
        return TelegramNotificationHandler(
            event_bot=event_bot,
            message_bot=message_bot,
            cache=cache,
            settings=settings,
            translator_factory=translator_factory,
            event_bus=event_bus,
            recipient_service=recipient_service,
        )

    @provide
    def get_teamtalk_reply_handler(
        self,
        connections: FromDishka[dict[str, TeamTalkConnection]],
    ) -> TeamTalkReplyHandler:
        """Provides the TeamTalk reply handler."""
        return TeamTalkReplyHandler(connections=connections)


class RequestProvider(Provider):
    """Provides request-scoped dependencies."""

    scope = Scope.REQUEST

    @provide
    def get_uow(self, factory: AsyncSessionFactoryType) -> IUnitOfWork:
        """Provides the Unit of Work."""
        return SqlModelUnitOfWork(factory)

    @provide
    def get_user_repo(self, uow: FromDishka[IUnitOfWork]) -> UserRepository:
        """Provides the UserRepository from the Unit of Work."""
        return uow.users

    @provide
    def get_ban_repo(self, uow: FromDishka[IUnitOfWork]) -> BanRepository:
        """Provides the BanRepository from the Unit of Work."""
        return uow.bans

    @provide
    def get_admin_repo(self, uow: FromDishka[IUnitOfWork]) -> AdminRepository:
        """Provides the AdminRepository from the Unit of Work."""
        return uow.admins

    @provide
    def get_subscriber_repo(self, uow: FromDishka[IUnitOfWork]) -> SubscriberRepository:
        """Provides the SubscriberRepository from the Unit of Work."""
        return uow.subscribers

    @provide
    def get_deeplink_repo(self, uow: FromDishka[IUnitOfWork]) -> DeeplinkRepository:
        """Provides the DeeplinkRepository from the Unit of Work."""
        return uow.deeplinks

    @provide
    def get_deeplink_service(
        self,
        uow: FromDishka[IUnitOfWork],
        subscription_service: FromDishka[SubscriptionService],
        cache: FromDishka[CacheService],
    ) -> DeeplinkService:
        """Provides a DeeplinkService."""
        return DeeplinkService(uow, subscription_service, cache)

    @provide
    def get_user_settings_service(
        self, uow: FromDishka[IUnitOfWork], cache: FromDishka[CacheService]
    ) -> UserSettingsService:
        """Provides a UserSettingsService."""
        return UserSettingsService(uow, cache)

    @provide
    def get_subscription_service(
        self,
        uow: FromDishka[IUnitOfWork],
        cache: FromDishka[CacheService],
    ) -> SubscriptionService:
        """Provides a SubscriptionService."""
        return SubscriptionService(uow, cache)

    @provide
    def get_moderation_service(
        self,
        uow: FromDishka[IUnitOfWork],
        subscription_service: FromDishka[SubscriptionService],
        cache: FromDishka[CacheService],
    ) -> ModerationService:
        """Provides a ModerationService."""
        return ModerationService(uow, subscription_service, cache)

    @provide
    def get_report_service(self, settings: FromDishka[Settings]) -> ReportService:
        """Provides a ReportService."""
        return ReportService(settings=settings)

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
        return await user_settings_service.get_or_create(
            user.id, settings.general.default_lang
        )

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
        lang_code = (
            user_settings.language_code
            if user_settings
            else settings.general.default_lang
        )
        return translator_factory(lang_code)

    @provide
    def get_tt_connection(
        self, connections: FromDishka[dict[str, TeamTalkConnection]]
    ) -> TeamTalkConnection:
        """Provides the active TeamTalk connection."""
        if not connections:
            raise NoActiveTeamTalkConnectionError
        return next(iter(connections.values()))
