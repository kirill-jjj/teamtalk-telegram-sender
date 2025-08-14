"""Handles processing of incoming TeamTalk messages."""

from __future__ import annotations

from collections.abc import Callable
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

from dishka import AsyncContainer
import pytalk

from bot.config import Settings
from bot.constants import TEAMTALK_PRIVATE_MESSAGE_TYPE
from bot.event_bus.bus import EventBus
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.command_router import CommandRouter
from bot.teamtalk_bot.events import PrivateMessageReceivedEvent
from bot.telegram_bot.formatters import (
    get_effective_server_name,
    get_tt_user_display_name,
)

if TYPE_CHECKING:
    from pytalk.message import Message as TeamTalkMessage

    from bot.teamtalk_bot.command_router import CommandRouter
    from bot.teamtalk_bot.connection import TeamTalkConnection


logger = logging.getLogger(__name__)

ttstr = pytalk.instance.sdk.ttstr


class MessageHandler:
    """Parses, routes, and handles incoming private messages from TeamTalk."""

    def __init__(
        self,
        dishka_container: AsyncContainer,
        connection: TeamTalkConnection,
        command_router: CommandRouter,
    ) -> None:
        """Initializes the message handler."""
        self.dishka_container = dishka_container
        self.connection = connection
        self.command_router = command_router

    async def route_message(self, tt_message: TeamTalkMessage) -> None:
        """Public method to handle an incoming TeamTalk message."""
        if not self._is_valid_message(tt_message):
            return

        async with (await self.dishka_container()) as request_container:
            settings = await request_container.get(Settings)
            cache = await request_container.get(CacheService)
            translator_factory = await request_container.get(
                Callable[[str], NullTranslations]
            )
            event_bus = await request_container.get(EventBus)

            translator = await self._get_translator(settings, cache, translator_factory)
            content = tt_message.content.strip()
            from_user = tt_message.user
            from_user_nickname = get_tt_user_display_name(from_user, translator)
            from_user_username = ttstr(from_user.username)

            logger.debug(
                "[%s] Private msg from %s: '%s'",
                self.connection.server_info.host,
                from_user_username,
                content[:50],
            )

            if content.startswith("/"):
                parts = content.split(maxsplit=1)
                cmd = parts[0].lower()
                args = parts[1] if len(parts) > 1 else None
                await self.command_router.route(cmd, args, tt_message, translator)
            else:
                server_name = get_effective_server_name(
                    self.connection.instance, translator, settings
                )
                server_key = (
                    f"{self.connection.server_info.host}:"
                    f"{self.connection.server_info.tcp_port}"
                )
                await event_bus.publish(
                    PrivateMessageReceivedEvent(
                        from_user_id=from_user.id,
                        from_user_nickname=from_user_nickname,
                        from_user_username=from_user_username,
                        content=content,
                        server_name=server_name,
                        connection_id=server_key,
                    )
                )

    async def _get_translator(
        self,
        settings: Settings,
        cache: CacheService,
        translator_factory: Callable[[str], NullTranslations],
    ) -> NullTranslations:
        """Determines the language for the reply and returns a translator."""
        admin_cfg = settings.telegram.admin_chat_id
        reply_lang = settings.general.default_lang
        if admin_cfg:
            admin_settings = await cache.get_user_settings(admin_cfg)
            if admin_settings and admin_settings.language_code:
                reply_lang = admin_settings.language_code
        return translator_factory(reply_lang)

    def _is_valid_message(self, tt_message: TeamTalkMessage) -> bool:
        """Performs initial checks to see if the message should be processed."""
        if not self.connection.instance:
            logger.warning("Handler has no connection instance, skipping message.")
            return False

        my_user_id = self.connection.instance.getMyUserID()
        if tt_message.from_id == my_user_id:
            return False  # Ignore messages from self

        return (
            tt_message.type is not None
            and tt_message.type == TEAMTALK_PRIVATE_MESSAGE_TYPE
        )
