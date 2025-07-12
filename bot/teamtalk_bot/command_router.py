"""Command router for TeamTalk bot."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.commands import (
    handle_tt_add_admin_command,
    handle_tt_help_command,
    handle_tt_remove_admin_command,
    handle_tt_subscribe_command,
    handle_tt_unknown_command,
    handle_tt_unsubscribe_command,
)

if TYPE_CHECKING:
    from gettext import GNUTranslations

    from pytalk.message import Message as TeamTalkMessage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bot.services_container import Services
    from bot.teamtalk_bot.connection import TeamTalkConnection


logger = logging.getLogger(__name__)


class CommandRouter:
    """Maps commands to their handlers and executes them."""

    def __init__(self, services: Services, connection: TeamTalkConnection) -> None:
        """Initializes the command router."""
        self.services = services
        self.connection = connection
        self.handlers = {
            tt_cmds.TT_CMD_SUBSCRIBE: handle_tt_subscribe_command,
            tt_cmds.TT_CMD_UNSUBSCRIBE: handle_tt_unsubscribe_command,
            tt_cmds.TT_CMD_ADD_ADMIN: handle_tt_add_admin_command,
            tt_cmds.TT_CMD_REMOVE_ADMIN: handle_tt_remove_admin_command,
            tt_cmds.TT_CMD_HELP: handle_tt_help_command,
        }

    async def route(
        self,
        cmd: str,
        args: str | None,
        tt_message: TeamTalkMessage,
        translator: GNUTranslations,
        session: AsyncSession,
    ) -> None:
        """Routes a command to the appropriate handler."""
        handler = self.handlers.get(cmd)
        if handler:
            kwargs = {
                "tt_message": tt_message,
                "translator": translator,
                "services": self.services,
                "_connection": self.connection,
            }
            if cmd in [tt_cmds.TT_CMD_ADD_ADMIN, tt_cmds.TT_CMD_REMOVE_ADMIN]:
                kwargs["args_str"] = args
            if cmd != tt_cmds.TT_CMD_HELP:
                kwargs["session"] = session
            await handler(**kwargs)
        else:
            await handle_tt_unknown_command(tt_message, translator, connection=self.connection)
