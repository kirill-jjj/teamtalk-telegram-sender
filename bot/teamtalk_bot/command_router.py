"""Command router for TeamTalk bot."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from gettext import GNUTranslations, NullTranslations
import logging
from typing import TYPE_CHECKING, cast

from bot.config import Settings
from bot.database.engine import AsyncSessionFactoryType
from bot.services.cache_service import CacheService
from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.commands import (
    on_add_admin,
    on_help,
    on_remove_admin,
    on_subscribe,
    on_unknown,
    on_unsubscribe,
)

if TYPE_CHECKING:
    from pytalk.message import Message as TeamTalkMessage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bot.teamtalk_bot.connection import TeamTalkConnection


logger = logging.getLogger(__name__)


class CommandRouter:
    """Maps commands to their handlers and executes them."""

    def __init__(
        self,
        settings: Settings,
        session_factory: AsyncSessionFactoryType,
        cache: CacheService,
        translator_factory: Callable[[str], GNUTranslations | NullTranslations],
        connection: TeamTalkConnection,
    ) -> None:
        """Initializes the command router."""
        self.settings = settings
        self.session_factory = session_factory
        self.cache = cache
        self.translator_factory = translator_factory
        self.connection = connection
        self.handlers = {
            tt_cmds.TT_CMD_SUBSCRIBE: on_subscribe,
            tt_cmds.TT_CMD_UNSUBSCRIBE: on_unsubscribe,
            tt_cmds.TT_CMD_ADD_ADMIN: on_add_admin,
            tt_cmds.TT_CMD_REMOVE_ADMIN: on_remove_admin,
            tt_cmds.TT_CMD_HELP: on_help,
        }

    async def route(
        self,
        cmd: str,
        args: str | None,
        tt_message: TeamTalkMessage,
        translator: GNUTranslations | NullTranslations,
        session: AsyncSession,
    ) -> None:
        """Routes a command to the appropriate handler."""
        handler = self.handlers.get(cmd)
        if handler:
            # Define a type for the handler function for clarity and type checking
            handler_type = Callable[..., Awaitable[None]]
            typed_handler = cast(handler_type, handler)

            kwargs = {
                "tt_message": tt_message,
                "translator": translator,
                "settings": self.settings,
                "session_factory": self.session_factory,
                "cache": self.cache,
                "translator_factory": self.translator_factory,
                "_connection": self.connection,
            }
            if cmd in [tt_cmds.TT_CMD_ADD_ADMIN, tt_cmds.TT_CMD_REMOVE_ADMIN]:
                kwargs["args_str"] = args
            if cmd != tt_cmds.TT_CMD_HELP:
                kwargs["session"] = session
            await typed_handler(**kwargs)
        else:
            await on_unknown(tt_message, translator, connection=self.connection)
