"""Handles processing of incoming TeamTalk messages."""

from __future__ import annotations

from collections.abc import Callable
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

import pytalk

from bot.config import Settings
from bot.constants import TEAMTALK_PRIVATE_MESSAGE_TYPE
from bot.event_bus.bus import EventBus
from bot.services.cache_service import CacheService
from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.command_handlers import (
    PrivateMessageCommandHandlers,
)
from bot.teamtalk_bot.events import PrivateMessageReceivedEvent
from bot.teamtalk_bot.formatters import (
    format_teamtalk_help_message,
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
        command_router: CommandRouter,
        event_bus: EventBus,
        settings: Settings,
        cache: CacheService,
        translator_factory: Callable[[str], NullTranslations],
        command_handlers: PrivateMessageCommandHandlers,
        connection: TeamTalkConnection,
    ) -> None:
        """Initializes the message handler with injected dependencies."""
        self.command_router = command_router
        self.event_bus = event_bus
        self.settings = settings
        self.cache = cache
        self.translator_factory = translator_factory
        self.command_handlers = command_handlers
        self.connection = connection

    async def route_message(self, tt_message: TeamTalkMessage) -> None:
        """Public method to handle an incoming TeamTalk message."""
        if not self.connection or not self._is_valid_message(tt_message):
            return

        translator = await self._get_translator()
        content = tt_message.content.strip()

        if content.startswith("/"):
            parts = content.split(maxsplit=1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else None

            known_commands = [
                tt_cmds.TT_CMD_SUBSCRIBE,
                tt_cmds.TT_CMD_UNSUBSCRIBE,
                tt_cmds.TT_CMD_ADD_ADMIN,
                tt_cmds.TT_CMD_REMOVE_ADMIN,
            ]

            if cmd == tt_cmds.TT_CMD_HELP:
                await self._on_help(tt_message, translator)
            elif cmd in known_commands:
                await self.command_router.route(
                    cmd, args, self.command_handlers, tt_message, translator
                )
            else:
                await self._on_unknown(tt_message, translator)
        else:
            await self._publish_private_message_event(tt_message, translator)

    async def _on_help(
        self, tt_message: TeamTalkMessage, translator: NullTranslations
    ) -> None:
        """Handles the /help command from a TeamTalk user."""
        tt_username_str = ttstr(tt_message.user.username)
        is_main_tt_admin = bool(
            self.settings.general.admin_username
            and tt_username_str == self.settings.general.admin_username
        )
        help_text = format_teamtalk_help_message(translator, is_admin=is_main_tt_admin)
        await self.command_handlers._reply_to_tt_message(tt_message.reply, help_text)

    async def _on_unknown(
        self, tt_message: TeamTalkMessage, translator: NullTranslations
    ) -> None:
        """Handles unknown commands received from a TeamTalk user."""
        _ = translator.gettext
        available_commands = ", ".join(
            [
                tt_cmds.TT_CMD_SUBSCRIBE,
                tt_cmds.TT_CMD_UNSUBSCRIBE,
                tt_cmds.TT_CMD_ADD_ADMIN,
                tt_cmds.TT_CMD_REMOVE_ADMIN,
                tt_cmds.TT_CMD_HELP,
            ]
        )
        reply_text = _("Unknown command. Available commands: {commands}.").format(
            commands=available_commands
        )
        await self.command_handlers._reply_to_tt_message(tt_message.reply, reply_text)
        if self.connection:
            logger.warning(
                "Unknown TT command from %s on %s: %s",
                ttstr(tt_message.user.username),
                self.connection.server_info.host,
                tt_message.content[:100],
            )

    async def _publish_private_message_event(
        self, tt_message: TeamTalkMessage, translator: NullTranslations
    ) -> None:
        """Publishes an event for a non-command private message."""
        if not self.connection or not self.connection.instance:
            return

        from_user = tt_message.user
        from_user_nickname = get_tt_user_display_name(from_user, translator)
        from_user_username = ttstr(from_user.username)

        logger.debug(
            "[%s] Private msg from %s: '%s'",
            self.connection.server_info.host,
            from_user_username,
            tt_message.content[:50],
        )

        server_name = get_effective_server_name(
            self.connection.instance, translator, self.settings
        )
        server_key = (
            f"{self.connection.server_info.host}:{self.connection.server_info.tcp_port}"
        )
        await self.event_bus.publish(
            PrivateMessageReceivedEvent(
                from_user_id=from_user.id,
                from_user_nickname=from_user_nickname,
                from_user_username=from_user_username,
                content=tt_message.content,
                server_name=server_name,
                connection_id=server_key,
            )
        )

    async def _get_translator(self) -> NullTranslations:
        """Determines the language for the reply and returns a translator."""
        admin_cfg = self.settings.telegram.admin_chat_id
        reply_lang = self.settings.general.default_lang
        if admin_cfg:
            admin_settings = self.cache.get_user_settings(admin_cfg)
            if admin_settings and admin_settings.language_code:
                reply_lang = admin_settings.language_code
        return self.translator_factory(reply_lang)

    def _is_valid_message(self, tt_message: TeamTalkMessage) -> bool:
        """Performs initial checks to see if the message should be processed."""
        if not self.connection or not self.connection.instance:
            logger.warning("Handler has no connection instance, skipping message.")
            return False

        my_user_id = self.connection.instance.getMyUserID()
        if tt_message.from_id == my_user_id:
            return False  # Ignore messages from self

        return (
            tt_message.type is not None
            and tt_message.type == TEAMTALK_PRIVATE_MESSAGE_TYPE
        )
