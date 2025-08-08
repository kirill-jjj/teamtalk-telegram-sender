# mypy: ignore-errors
"""Handles sending Telegram notifications in response to domain events."""

from collections.abc import Callable
from gettext import NullTranslations
from html import escape
import logging
from typing import cast

from aiogram.utils.formatting import Bold, Text
from sqlalchemy import and_, or_
from sqlmodel import select

from bot.config import Settings
from bot.constants import NOTIFICATION_EVENT_JOIN, NOTIFICATION_EVENT_LEAVE
from bot.database.engine import AsyncSessionFactoryType
from bot.event_bus.bus import EventBus
from bot.models import MutedUser, MuteListMode, NotificationSetting, UserSettings
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.events import (
    AdminStatusChangedEvent,
    PrivateMessageReceivedEvent,
    ReplyToTeamTalkUserEvent,
    UserJoinedEvent,
    UserLeftEvent,
)
from bot.telegram_bot.types.bots import EventBot, MessageBot
from bot.telegram_bot.utils import (
    broadcast_to_users,
    send_telegram_message,
    update_user_bot_commands,
)

logger = logging.getLogger(__name__)


class TelegramNotificationHandler:
    """Handles domain events and sends notifications to Telegram."""

    def __init__(
        self,
        event_bot: EventBot,
        message_bot: MessageBot,
        session_factory: AsyncSessionFactoryType,
        cache: CacheService,
        settings: Settings,
        translator_factory: Callable[[str], NullTranslations],
        event_bus: EventBus,
    ) -> None:
        """Initializes the TelegramNotificationHandler."""
        self.event_bot = event_bot
        self.message_bot = message_bot
        self.session_factory = session_factory
        self.cache = cache
        self.settings = settings
        self.translator_factory = translator_factory
        self.event_bus = event_bus

    async def handle_user_joined(self, event: UserJoinedEvent) -> None:
        """Handles the UserJoinedEvent and sends notifications."""
        await self._send_join_leave_notification(NOTIFICATION_EVENT_JOIN, event)

    async def handle_user_left(self, event: UserLeftEvent) -> None:
        """Handles the UserLeftEvent and sends notifications."""
        await self._send_join_leave_notification(NOTIFICATION_EVENT_LEAVE, event)

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

    async def _get_recipients(
        self, username_to_check: str, event_type: str
    ) -> list[tuple[int, str | None]]:
        """Gets the list of recipients for a notification."""
        subscriber_ids = list(self.cache.get_all_subscriber_ids())
        if not subscriber_ids:
            return []

        async with self.session_factory() as session:
            stmt = select(
                UserSettings.telegram_id,
                UserSettings.language_code,
            ).join(
                MutedUser,
                and_(
                    UserSettings.telegram_id == MutedUser.user_settings_telegram_id,
                    MutedUser.muted_teamtalk_username == username_to_check,
                ),
                isouter=True,
            )

            stmt = stmt.where(UserSettings.telegram_id.in_(subscriber_ids))  # type: ignore[attr-defined]
            stmt = stmt.where(
                UserSettings.notification_settings != NotificationSetting.NONE
            )

            if event_type == NOTIFICATION_EVENT_JOIN:
                stmt = stmt.where(
                    UserSettings.notification_settings != NotificationSetting.JOIN_OFF
                )
            elif event_type == NOTIFICATION_EVENT_LEAVE:
                stmt = stmt.where(
                    UserSettings.notification_settings != NotificationSetting.LEAVE_OFF
                )

            mute_logic = or_(
                and_(
                    UserSettings.mute_list_mode == MuteListMode.blacklist.value,  # type: ignore[arg-type]
                    MutedUser.id.is_(None),  # type: ignore[union-attr]
                ),
                and_(
                    UserSettings.mute_list_mode == MuteListMode.whitelist.value,  # type: ignore[arg-type]
                    MutedUser.id.is_not(None),  # type: ignore[union-attr]
                ),
            )
            stmt = stmt.where(mute_logic)

            result = await session.execute(stmt)
            return cast(list[tuple[int, str | None]], result.all())

    async def _send_join_leave_notification(
        self, event_type: str, event: UserJoinedEvent | UserLeftEvent
    ) -> None:
        """Core logic to send join/leave notifications based on an event."""
        if not event.username:
            logger.warning("User event with empty username. Skipping.")
            return

        if event.username in self.settings.teamtalk.global_ignore_usernames:
            logger.debug("User %s is globally ignored. Skipping.", event.username)
            return

        recipients = await self._get_recipients(event.username, event_type)
        if not recipients:
            logger.debug(
                "No recipients for %s event for user %s.", event_type, event.username
            )
            return

        logger.info(
            "Sending %s notifications for %s to %d users.",
            event_type,
            event.username,
            len(recipients),
        )

        await broadcast_to_users(
            bot_instance_to_use=self.event_bot,
            recipients_with_lang=recipients,
            text_generator=lambda lang_code: self._generate_join_leave_text(
                event,
                event_type,
                lang_code or self.settings.general.default_lang,
            ),
            cache=self.cache,
        )
