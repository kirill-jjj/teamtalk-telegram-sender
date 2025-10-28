"""Service-related Dishka providers for dependency injection."""

from collections.abc import Callable
from gettext import NullTranslations

from aiogram.types import User
from dishka import FromDishka, Provider, Scope, provide, provide_all

from bot.command_bus.bus import CommandBus
from bot.config import Settings
from bot.database.engine import AsyncSessionFactoryType
from bot.database.uow import IUnitOfWork
from bot.event_bus.bus import EventBus
from bot.services.admin_service import AdminService
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.moderation_service import ModerationService
from bot.services.notification_service import NotificationRecipientService
from bot.services.report_service import ReportService
from bot.services.schemas import SettingsViewDTO
from bot.services.subscription_service import SubscriptionService
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.types.bots import EventBot


class ServicesProvider(Provider):
    """Provides service-layer dependencies."""

    scope = Scope.REQUEST

    @provide(scope=Scope.APP)
    @staticmethod
    def get_notification_recipient_service(
        session_factory: FromDishka[AsyncSessionFactoryType],
        cache: FromDishka[CacheService],
    ) -> NotificationRecipientService:
        """Provides a NotificationRecipientService."""
        return NotificationRecipientService(session_factory, cache)

    @provide(scope=Scope.REQUEST)
    @staticmethod
    def get_report_service(
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

    @provide(scope=Scope.REQUEST)
    @staticmethod
    def get_admin_service(
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
        DeeplinkService, UserSettingsService, SubscriptionService, scope=Scope.REQUEST
    )

    @provide(scope=Scope.REQUEST)
    @staticmethod
    def get_moderation_service(
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

    @provide(provides=SettingsViewDTO | None, scope=Scope.REQUEST)
    @staticmethod
    async def get_user_settings_optional(
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

    @provide(scope=Scope.REQUEST)
    @staticmethod
    def get_user_settings_guaranteed(
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

    @provide(provides=NullTranslations, scope=Scope.REQUEST)
    @staticmethod
    def get_translator(
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
