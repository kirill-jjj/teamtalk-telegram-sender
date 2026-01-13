"""Telegram-related Dishka providers for dependency injection."""

from collections.abc import Callable
from gettext import NullTranslations
from typing import cast

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject, User
from dishka import AsyncContainer, Provider, Scope, provide

from bot.config import Settings
from bot.event_bus.bus import EventBus
from bot.services.cache_service import CacheService
from bot.services.notification_service import NotificationRecipientService
from bot.telegram_bot.handlers.event_subscribers import TelegramNotificationHandler
from bot.telegram_bot.types.bots import EventBot, MessageBot


def _create_bot(token: str) -> Bot:
    """Creates a Bot instance with default properties."""
    default_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    return Bot(token=token, default=default_props)


class TelegramProvider(Provider):
    """Provides Telegram-related dependencies."""

    scope = Scope.APP

    @provide(provides=EventBot, scope=Scope.APP)
    @staticmethod
    def get_bot_event(settings: Settings) -> EventBot:
        """Provides the event-handling Bot instance."""
        bot = _create_bot(token=settings.telegram.event_token)
        return cast("EventBot", bot)

    @provide(provides=MessageBot, scope=Scope.APP)
    @staticmethod
    def get_bot_message(settings: Settings) -> MessageBot:
        """Provides the message-sending Bot instance."""
        token = settings.telegram.message_token or settings.telegram.event_token
        bot = _create_bot(token=token)
        return cast("MessageBot", bot)

    @provide(scope=Scope.APP)
    @staticmethod
    def get_dispatcher() -> Dispatcher:
        """Provides the aiogram Dispatcher."""
        return Dispatcher()

    @provide(scope=Scope.APP)
    @staticmethod
    def get_telegram_notification_handler(  # noqa: PLR0917
        event_bot: EventBot,
        message_bot: MessageBot,
        cache: CacheService,
        settings: Settings,
        translator_factory: Callable[[str | None], NullTranslations],
        event_bus: EventBus,
        recipient_service: NotificationRecipientService,
        app_container: AsyncContainer,
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
            app_container=app_container,
        )

    @provide(scope=Scope.REQUEST)
    @staticmethod
    def get_user_from_event(event: TelegramObject) -> User | None:
        """Extracts the User object from the incoming event, if it exists.

        AiogramProvider provides the `event: TelegramObject`.
        This provider makes the `User` available for other dependencies.
        """
        return getattr(event, "from_user", None)
