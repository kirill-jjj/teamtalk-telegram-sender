"""Routes TeamTalk commands to appropriate handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bot.teamtalk_bot import command_constants as tt_cmds

if TYPE_CHECKING:
    from gettext import NullTranslations

    from pytalk.message import Message as TeamTalkMessage

    from bot.database.uow import IUnitOfWork
    from bot.teamtalk_bot.command_handlers import PrivateMessageCommandHandlers

logger = logging.getLogger(__name__)


class CommandRouter:
    """Maps commands to their handlers and executes them."""

    def __init__(self) -> None:
        """Initializes the command router."""

    @staticmethod
    async def route(  # noqa: PLR0917
        cmd: str,
        args: str | None,
        handlers: PrivateMessageCommandHandlers,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        uow: IUnitOfWork,
    ) -> None:
        """Routes a command to the appropriate handler."""
        # The caller (MessageHandler) will now handle 'help' and 'unknown' commands.
        # This router is only for commands that have a dedicated handler method.
        if cmd == tt_cmds.TT_CMD_SUBSCRIBE:
            await handlers.on_subscribe(uow, tt_message, translator)
        elif cmd == tt_cmds.TT_CMD_UNSUBSCRIBE:
            await handlers.on_unsubscribe(uow, tt_message, translator)
        elif cmd == tt_cmds.TT_CMD_ADD_ADMIN:
            await handlers.on_add_admin(uow, tt_message, translator, args)
        elif cmd == tt_cmds.TT_CMD_REMOVE_ADMIN:
            await handlers.on_remove_admin(uow, tt_message, translator, args)
        else:
            # This else should ideally not be reached if the caller filters commands.
            logger.warning("CommandRouter received an unhandled command: %s", cmd)
