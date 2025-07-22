"""Handles processing of incoming TeamTalk messages."""

from __future__ import annotations

import gettext
import logging
from typing import TYPE_CHECKING

import pytalk

from bot.constants import TEAMTALK_PRIVATE_MESSAGE_TYPE
from bot.teamtalk_bot.command_router import CommandRouter
from bot.teamtalk_bot.utils import forward_tt_message_to_telegram_admin

if TYPE_CHECKING:
    from pytalk.message import Message as TeamTalkMessage

    from bot.services_container import Services
    from bot.teamtalk_bot.connection import TeamTalkConnection


logger = logging.getLogger(__name__)

ttstr = pytalk.instance.sdk.ttstr


class MessageHandler:
    """Parses, routes, and handles incoming private messages from TeamTalk."""

    def __init__(self, services: Services, connection: TeamTalkConnection) -> None:
        """Initializes the message handler."""
        self.services = services
        self.connection = connection
        self.command_router = CommandRouter(services, connection)

    async def handle_message(self, tt_message: TeamTalkMessage) -> None:
        """Public method to handle an incoming TeamTalk message."""
        if not self._is_valid_message(tt_message):
            return

        translator = self._get_translator()
        sender = ttstr(tt_message.user.username)
        content = tt_message.content.strip()
        logger.debug(
            "[%s] Private msg from %s: '%s'", self.connection.server_info.host, sender, content[:50]
        )

        async with self.services.session_factory() as session:
            if content.startswith("/"):
                parts = content.split(maxsplit=1)
                cmd = parts[0].lower()
                args = parts[1] if len(parts) > 1 else None
                await self.command_router.route(cmd, args, tt_message, translator, session)
            else:
                await forward_tt_message_to_telegram_admin(
                    message=tt_message, services=self.services, translator=translator
                )

    def _get_translator(self) -> gettext.GNUTranslations | gettext.NullTranslations:
        """Determines the language for the reply and returns a translator."""
        admin_cfg = self.services.config.telegram.admin_chat_id
        reply_lang = self.services.config.general.default_lang
        if admin_cfg:
            admin_settings = self.services.cache.get_user_settings(admin_cfg)
            if admin_settings and admin_settings.language_code:
                reply_lang = admin_settings.language_code
        return self.services.get_translator(reply_lang)

    def _is_valid_message(self, tt_message: TeamTalkMessage) -> bool:
        """Performs initial checks to see if the message should be processed."""
        if not self.connection.instance:
            logger.warning("Handler has no connection instance, skipping message.")
            return False

        my_user_id = self.connection.instance.getMyUserID()
        if tt_message.from_id == my_user_id:
            return False  # Ignore messages from self

        return tt_message.type is not None and tt_message.type == TEAMTALK_PRIVATE_MESSAGE_TYPE
