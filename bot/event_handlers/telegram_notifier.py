"""Handles sending Telegram notifications in response to domain events."""

import asyncio
from collections.abc import Callable
from gettext import NullTranslations
from html import escape
import logging

from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.formatting import Bold, Text
from pytalk.user import User as TeamTalkUser

from bot.config import Settings
from bot.constants import DEFAULT_LANGUAGE
from bot.core.enums import NotificationType
from bot.database.engine import AsyncSessionFactoryType
from bot.database.uow import SqlModelUnitOfWork
from bot.event_bus.bus import EventBus
from bot.services.cache_service import CacheService
from bot.services.notification_service import (
    NotificationRecipientService,
    should_send_silently,
)
from bot.services.subscription_service import SubscriptionService
from bot.teamtalk_bot.events import (
    AdminStatusChangedEvent,
    PrivateMessageReceivedEvent,
    ReplyToTeamTalkUserEvent,
    UserJoinedEvent,
    UserLeftEvent,
)
from bot.telegram_bot.api import send_telegram_message
from bot.telegram_bot.commands import update_user_bot_commands
from bot.telegram_bot.types.bots import EventBot, MessageBot

logger = logging.getLogger(__name__)


class TelegramNotificationHandler:
    """Handles domain events and sends notifications to Telegram."""

    def __init__(
        self,
        event_bot: EventBot,
        message_bot: MessageBot,
        cache: CacheService,
        settings: Settings,
        translator_factory: Callable[[str | None], NullTranslations],
        event_bus: EventBus,
        recipient_service: NotificationRecipientService,
        session_factory: AsyncSessionFactoryType,
    ) -> None:
        """Initializes the TelegramNotificationHandler."""
        self.event_bot = event_bot
        self.message_bot = message_bot
        self.cache = cache
        self.settings = settings
        self.translator_factory = translator_factory
        self.event_bus = event_bus
        self.recipient_service = recipient_service
        self.session_factory = session_factory

    async def handle_user_joined(self, event: UserJoinedEvent) -> None:
        """Handles the UserJoinedEvent and sends notifications."""
        if event.username in self.settings.teamtalk.global_ignore_usernames:
            logger.debug("User %s is globally ignored. Skipping.", event.username)
            return

        recipients = await self.recipient_service.find_recipients(
            event.username, NotificationType.JOIN
        )
        if not recipients:
            return

        await self.broadcast_to_users(
            recipients_with_lang=recipients,
            text_generator=lambda lang_code: self._generate_join_leave_text(
                event,
                NotificationType.JOIN,
                lang_code or self.settings.general.default_lang,
            ),
            online_users_cache_for_instance=event.online_users_cache,
        )

    async def handle_user_left(self, event: UserLeftEvent) -> None:
        """Handles the UserLeftEvent and sends notifications."""
        if event.username in self.settings.teamtalk.global_ignore_usernames:
            logger.debug("User %s is globally ignored. Skipping.", event.username)
            return

        recipients = await self.recipient_service.find_recipients(
            event.username, NotificationType.LEAVE
        )
        if not recipients:
            return

        await self.broadcast_to_users(
            recipients_with_lang=recipients,
            text_generator=lambda lang_code: self._generate_join_leave_text(
                event,
                NotificationType.LEAVE,
                lang_code or self.settings.general.default_lang,
            ),
            online_users_cache_for_instance=event.online_users_cache,
        )

    async def handle_admin_status_changed(
        self,
        event: AdminStatusChangedEvent,
    ) -> None:
        """Handles the AdminStatusChangedEvent and updates user commands."""
        lang_code = event.lang_code or self.settings.general.default_lang
        translator = self.translator_factory(lang_code)
        await update_user_bot_commands(
            telegram_id=event.telegram_id,
            new_lang_code=lang_code,
            cache=self.cache,
            bot=self.event_bot,
            translator=translator,
        )

    async def handle_private_message(
        self,
        event: PrivateMessageReceivedEvent,
    ) -> None:
        """Handles the PrivateMessageReceivedEvent and forwards it to the admin."""
        admin_chat_id = self.settings.telegram.admin_chat_id
        if not admin_chat_id:
            logger.debug(
                "No admin_chat_id configured, skipping private message forwarding."
            )
            return

        translator = self._get_translator_for_admin()
        _ = translator.gettext

        content = Text(
            _("Message from server "),
            Bold(event.server_name),
            "\n",
            _("From "),
            Bold(event.from_user_nickname),
            ":\n\n",
            event.content,
        )

        was_sent = await send_telegram_message(
            bot_instance=self.message_bot,
            chat_id=admin_chat_id,
            **content.as_kwargs(),
        )

        reply_text = (
            _("Message sent to Telegram successfully.")
            if was_sent
            else _("Failed to deliver message to Telegram")
        )

        await self.event_bus.publish(
            ReplyToTeamTalkUserEvent(
                connection_id=event.connection_id,
                user_id=event.from_user_id,
                text=reply_text,
            )
        )

    def _get_translator_for_admin(self) -> NullTranslations:
        """Gets the appropriate translator for messaging the admin."""
        admin_chat_id = self.settings.telegram.admin_chat_id
        lang_code = self.settings.general.default_lang
        if admin_chat_id:
            admin_settings = self.cache.get_user_settings(admin_chat_id)
            if admin_settings and admin_settings.language_code:
                lang_code = admin_settings.language_code
        return self.translator_factory(lang_code)

    def _generate_join_leave_text(
        self,
        event: UserJoinedEvent | UserLeftEvent,
        event_type: NotificationType,
        lang_code: str,
    ) -> str:
        """Generates the localized text for a join/leave notification."""
        translator = self.translator_factory(lang_code)
        _ = translator.gettext

        template = (
            _("{user_nickname} joined server {server_name}")
            if event_type == NotificationType.JOIN
            else _("{user_nickname} left server {server_name}")
        )
        return template.format(
            user_nickname=escape(event.user_nickname),
            server_name=escape(event.server_name),
        )

    async def broadcast_to_users(
        self,
        recipients_with_lang: list[tuple[int, str | None]],
        text_generator: Callable[[str | None], str],
        online_users_cache_for_instance: dict[int, TeamTalkUser] | None = None,
        reply_markup_generator: Callable[[str | None, int], InlineKeyboardMarkup | None]
        | None = None,
    ) -> None:
        """Sends localized messages to recipients and handles errors individually."""
        if not self.event_bot:
            logger.error("No Telegram bot instance provided to broadcast_to_users.")
            return

        tasks = []
        for chat_id, lang_code in recipients_with_lang:
            tasks.append(
                asyncio.create_task(
                    self._send_and_handle_broadcast_error(
                        chat_id=chat_id,
                        lang_code=lang_code,
                        text_generator=text_generator,
                        online_users_cache_for_instance=online_users_cache_for_instance,
                        reply_markup_generator=reply_markup_generator,
                    )
                )
            )

        if tasks:
            await asyncio.gather(*tasks)

    async def _send_and_handle_broadcast_error(
        self,
        chat_id: int,
        lang_code: str | None,
        text_generator: Callable[[str | None], str],
        online_users_cache_for_instance: dict[int, TeamTalkUser] | None,
        reply_markup_generator: Callable[[str | None, int], InlineKeyboardMarkup | None]
        | None,
    ) -> None:
        """Helper coroutine to send a message and handle Forbidden error."""
        try:
            language_code = lang_code or DEFAULT_LANGUAGE
            text = text_generator(language_code)
            current_reply_markup = (
                reply_markup_generator(language_code, chat_id)
                if reply_markup_generator
                else None
            )

            send_silently = should_send_silently(
                chat_id, self.cache, online_users_cache_for_instance
            )

            await send_telegram_message(
                bot_instance=self.event_bot,
                chat_id=chat_id,
                reply_markup=current_reply_markup,
                disable_notification=send_silently,
                text=text,
            )
        except TelegramForbiddenError:
            logger.warning(
                "User %s blocked the bot or is deactivated. Deleting all user data...",
                chat_id,
            )
            # Use a default translator for the deletion process logs/messages
            default_translator = self.translator_factory(DEFAULT_LANGUAGE)
            async with SqlModelUnitOfWork(self.session_factory) as uow:
                subscription_service = SubscriptionService(uow, self.cache)
                await subscription_service.delete_profile(
                    uow, chat_id, default_translator
                )
                await uow.commit()
        except Exception:
            logger.critical(
                "An unexpected error occurred during broadcast to chat_id %s.",
                chat_id,
            )
