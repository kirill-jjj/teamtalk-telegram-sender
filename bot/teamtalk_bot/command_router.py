"""Routes TeamTalk commands to appropriate handlers."""

from __future__ import annotations

from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

from pytalk.message import Message as TeamTalkMessage

from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.command_handlers import PrivateMessageCommandHandlers

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CommandRouter:
    """Maps commands to their handlers and executes them."""

    def __init__(self) -> None:
        """Initializes the command router."""

    async def route(
        self,
        cmd: str,
        args: str | None,
        handlers: PrivateMessageCommandHandlers,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
    ) -> None:
        """Routes a command to the appropriate handler."""
        # The caller (MessageHandler) will now handle 'help' and 'unknown' commands.
        # This router is only for commands that have a dedicated handler method.
        if cmd == tt_cmds.TT_CMD_SUBSCRIBE:
            await handlers.on_subscribe(tt_message, translator)
        elif cmd == tt_cmds.TT_CMD_UNSUBSCRIBE:
            await handlers.on_unsubscribe(tt_message, translator)
        elif cmd == tt_cmds.TT_CMD_ADD_ADMIN:
            await handlers.on_add_admin(tt_message, translator, args)
        elif cmd == tt_cmds.TT_CMD_REMOVE_ADMIN:
            await handlers.on_remove_admin(tt_message, translator, args)
        else:
            # This else should ideally not be reached if the caller filters commands.
            logger.warning("CommandRouter received an unhandled command: %s", cmd)
