"""Dishka providers for dependency injection."""

from collections.abc import Callable
import gettext
from gettext import NullTranslations
from typing import cast

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject, User
from dishka import FromDishka, Provider, Scope, provide, provide_all

from bot.command_bus.bus import CommandBus
from bot.config import Settings
from bot.core.languages import DOMAIN, LOCALE_DIR, LanguageInfo, discover_languages
from bot.database.engine import AsyncSessionFactoryType, create_session_factory
from bot.database.uow import IUnitOfWork, SqlModelUnitOfWork
from bot.event_bus.bus import EventBus
from bot.event_handlers.telegram_notifier import TelegramNotificationHandler
from bot.services.admin_service import AdminService
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.moderation_service import ModerationService
from bot.services.notification_service import NotificationRecipientService
from bot.services.report_service import ReportService
from bot.services.schemas import SettingsViewDTO
from bot.services.subscription_service import SubscriptionService
from bot.services.user_settings_service import UserSettingsService
from bot.teamtalk_bot.command_handlers import PrivateMessageCommandHandlers
from bot.teamtalk_bot.command_router import CommandRouter
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.message_handler import MessageHandler
from bot.telegram_bot.types.bots import EventBot, MessageBot


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


def _create_bot(token: str) -> Bot:
    """Creates a Bot instance with default properties."""
    default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    return Bot(token=token, default=default_props)


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
    def get_translator_cache(self) -> dict[str, NullTranslations]:
        """Provides a cache for translator objects."""
        return {}

    @provide
    def get_available_languages(self) -> list[LanguageInfo]:
        """Provides a list of available languages."""
        return discover_languages()

    @provide
    def get_translator_factory(
        self, translator_cache: dict[str, NullTranslations]
    ) -> Callable[[str | None], NullTranslations]:
        """Provides a factory for creating translators."""
        return create_translator_factory(translator_cache)

    @provide(provides=Callable[[str], NullTranslations])
    def get_str_translator_factory(
        self, translator_factory: FromDishka[Callable[[str | None], NullTranslations]]
    ) -> Callable[[str], NullTranslations]:
        """Provides a factory for creating translators that only accepts strings."""

        def factory(lang_code: str) -> NullTranslations:
            return translator_factory(lang_code)

        return factory

    @provide
    def get_event_bus(self) -> EventBus:
        """Provides the application-wide event bus."""
        return EventBus()

    @provide
    def get_command_bus(self) -> CommandBus:
        """Provides the application-wide command bus."""
        return CommandBus()

    @provide
    def get_cache_service(self) -> CacheService:
        """Provides the application-wide cache service."""
        return CacheService(
            user_settings_cache={}, admin_ids_cache=set(), subscribed_users_cache=set()
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
        translator_factory: FromDishka[Callable[[str | None], NullTranslations]],
        event_bus: FromDishka[EventBus],
        recipient_service: FromDishka[NotificationRecipientService],
        session_factory: FromDishka[AsyncSessionFactoryType],
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
            session_factory=session_factory,
        )


class RequestProvider(Provider):
    """Provides request-scoped dependencies."""

    scope = Scope.REQUEST

    @provide
    def get_report_service(
        self,
        settings: FromDishka[Settings],
        uow: FromDishka[IUnitOfWork],
        bot: FromDishka[EventBot],
        command_bus: FromDishka[CommandBus],
    ) -> ReportService:
        """Provides a ReportService."""
        return ReportService(
            settings=settings,
            uow=uow,
            bot=bot,
            command_bus=command_bus,
        )

    @provide
    def get_command_router(self) -> CommandRouter:
        """Provides a CommandRouter instance."""
        return CommandRouter()

    @provide
    def get_message_handler(
        self,
        command_router: FromDishka[CommandRouter],
        event_bus: FromDishka[EventBus],
        settings: FromDishka[Settings],
        cache: FromDishka[CacheService],
        translator_factory: FromDishka[Callable[[str | None], NullTranslations]],
        command_handlers: FromDishka[PrivateMessageCommandHandlers],
        connection: FromDishka[TeamTalkConnection],
    ) -> MessageHandler:
        """Provides a MessageHandler instance for a request."""
        return MessageHandler(
            command_router=command_router,
            event_bus=event_bus,
            settings=settings,
            cache=cache,
            translator_factory=translator_factory,
            command_handlers=command_handlers,
            connection=connection,
        )

    @provide
    def get_tt_pm_handlers(
        self,
        settings: FromDishka[Settings],
        cache: FromDishka[CacheService],
        deeplink_service: FromDishka[DeeplinkService],
        admin_service: FromDishka[AdminService],
        uow: FromDishka[IUnitOfWork],
    ) -> PrivateMessageCommandHandlers:
        """Provides an instance of PrivateMessageCommandHandlers."""
        return PrivateMessageCommandHandlers(
            settings=settings,
            cache=cache,
            deeplink_service=deeplink_service,
            admin_service=admin_service,
            uow=uow,
        )

    @provide
    def get_uow(
        self,
        factory: AsyncSessionFactoryType,
    ) -> IUnitOfWork:
        """Provides the Unit of Work."""
        return SqlModelUnitOfWork(
            session_factory=factory,
        )

    @provide
    def get_admin_service(
        self,
        uow: FromDishka[IUnitOfWork],
        cache: FromDishka[CacheService],
        event_bus: FromDishka[EventBus],
        settings: FromDishka[Settings],
    ) -> AdminService:
        """Provides an AdminService."""
        return AdminService(
            uow=uow,
            cache=cache,
            event_bus=event_bus,
            settings=settings,
        )

    services = provide_all(
        DeeplinkService,
        UserSettingsService,
        SubscriptionService,
    )

    @provide
    def get_moderation_service(
        self,
        uow: FromDishka[IUnitOfWork],
        subscription_service: FromDishka[SubscriptionService],
        cache: FromDishka[CacheService],
        command_bus: FromDishka[CommandBus],
        settings: FromDishka[Settings],
    ) -> ModerationService:
        """Provides a ModerationService."""
        return ModerationService(
            uow=uow,
            subscription_service=subscription_service,
            cache=cache,
            command_bus=command_bus,
            settings=settings,
        )

    @provide
    def get_user_from_event(self, event: TelegramObject) -> User | None:
        """Extracts the User object from the incoming event, if it exists.

        AiogramProvider provides the `event: TelegramObject`.
        This provider makes the `User` available for other dependencies.
        """
        return getattr(event, "from_user", None)

    @provide(provides=SettingsViewDTO | None)
    async def get_user_settings_optional(
        self,
        user: User | None,
        user_settings_service: UserSettingsService,
        settings: Settings,
        uow: FromDishka[IUnitOfWork],
    ) -> SettingsViewDTO | None:
        """Provides SettingsViewDTO if a user is present in the event."""
        if not user:
            return None
        async with uow:
            return await user_settings_service.get_user_settings_view(
                uow, user.id, settings.general.default_lang
            )

    @provide
    def get_user_settings_guaranteed(
        self,
        user_settings: SettingsViewDTO | None,
    ) -> SettingsViewDTO:
        """Provides a guaranteed SettingsViewDTO object.

        Raises:
            ValueError: If SettingsViewDTO cannot be provided because no user
                        is present in the event context.
        """
        if user_settings is None:
            raise ValueError
        return user_settings

    @provide(provides=NullTranslations)
    def get_translator(
        self,
        user_settings: SettingsViewDTO | None,
        settings: Settings,
        translator_factory: Callable[[str | None], NullTranslations],
    ) -> NullTranslations:
        """Provides a translator for the current user's language."""
        lang_code = (
            user_settings.language_code
            if user_settings
            else settings.general.default_lang
        )
        return translator_factory(lang_code)
