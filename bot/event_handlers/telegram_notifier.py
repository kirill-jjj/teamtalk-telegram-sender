"""Handles sending Telegram notifications in response to domain events."""

from collections.abc import Callable
from gettext import NullTranslations
from html import escape
import logging

from aiogram.utils.formatting import Bold, Text

from bot.config import Settings
from bot.constants import NOTIFICATION_EVENT_JOIN, NOTIFICATION_EVENT_LEAVE
from bot.event_bus.bus import EventBus
from bot.services.cache_service import CacheService
from bot.services.notification_service import NotificationRecipientService
from bot.teamtalk_bot.events import (
    AdminStatusChangedEvent,
    PrivateMessageReceivedEvent,
    ReplyToTeamTalkUserEvent,
    UserJoinedEvent,
    UserLeftEvent,
)
from bot.telegram_bot.api import broadcast_to_users, send_telegram_message
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
        translator_factory: Callable[[str], NullTranslations],
        event_bus: EventBus,
        recipient_service: NotificationRecipientService,
    ) -> None:
        """Initializes the TelegramNotificationHandler."""
        self.event_bot = event_bot
        self.message_bot = message_bot
        self.cache = cache
        self.settings = settings
        self.translator_factory = translator_factory
        self.event_bus = event_bus
        self.recipient_service = recipient_service

    async def handle_user_joined(self, event: UserJoinedEvent) -> None:
        """Handles the UserJoinedEvent and sends notifications."""
        if event.username in self.settings.teamtalk.global_ignore_usernames:
            logger.debug("User %s is globally ignored. Skipping.", event.username)
            return

        recipients = await self.recipient_service.find_recipients(
            event.username, NOTIFICATION_EVENT_JOIN
        )
        if not recipients:
            return

        await broadcast_to_users(
            bot_instance_to_use=self.event_bot,
            recipients_with_lang=recipients,
            text_generator=lambda lang_code: self._generate_join_leave_text(
                event,
                NOTIFICATION_EVENT_JOIN,
                lang_code or self.settings.general.default_lang,
            ),
            cache=self.cache,
            online_users_cache_for_instance=event.online_users_cache,
        )

    async def handle_user_left(self, event: UserLeftEvent) -> None:
        """Handles the UserLeftEvent and sends notifications."""
        if event.username in self.settings.teamtalk.global_ignore_usernames:
            logger.debug("User %s is globally ignored. Skipping.", event.username)
            return

        recipients = await self.recipient_service.find_recipients(
            event.username, NOTIFICATION_EVENT_LEAVE
        )
        if not recipients:
            return

        await broadcast_to_users(
            bot_instance_to_use=self.event_bot,
            recipients_with_lang=recipients,
            text_generator=lambda lang_code: self._generate_join_leave_text(
                event,
                NOTIFICATION_EVENT_LEAVE,
                lang_code or self.settings.general.default_lang,
            ),
            cache=self.cache,
            online_users_cache_for_instance=event.online_users_cache,
        )

    async def handle_admin_status_changed(self, event: AdminStatusChangedEvent) -> None:
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

    async def handle_private_message(self, event: PrivateMessageReceivedEvent) -> None:
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
            cache=self.cache,
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
        event_type: str,
        lang_code: str,
    ) -> str:
        """Generates the localized text for a join/leave notification."""
        translator = self.translator_factory(lang_code)
        _ = translator.gettext

        template = (
            _("{user_nickname} joined server {server_name}")
            if event_type == NOTIFICATION_EVENT_JOIN
            else _("{user_nickname} left server {server_name}")
        )
        return template.format(
            user_nickname=escape(event.user_nickname),
            server_name=escape(event.server_name),
        )
