"""Routes TeamTalk commands to appropriate handlers."""

from __future__ import annotations

from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

from dishka import AsyncContainer
from pytalk.message import Message as TeamTalkMessage

from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.command_handlers import PrivateMessageCommandHandlers
from bot.teamtalk_bot.commands import on_help, on_unknown

if TYPE_CHECKING:
    from bot.teamtalk_bot.connection import TeamTalkConnection

logger = logging.getLogger(__name__)


class CommandRouter:
    """Maps commands to their handlers and executes them."""

    def __init__(
        self,
        dishka_container: AsyncContainer,
        connection: TeamTalkConnection,
    ) -> None:
        """Initializes the command router."""
        self.dishka_container = dishka_container
        self.connection = connection

    async def route(
        self,
        cmd: str,
        args: str | None,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
    ) -> None:
        """Routes a command to the appropriate handler with dependency injection."""
        # on_help and on_unknown do not require complex dependencies,
        # they can be left as is
        if cmd == tt_cmds.TT_CMD_HELP:
            async with self.dishka_container(
                context={TeamTalkMessage: tt_message, NullTranslations: translator}
            ) as request_container:
                on_help_callable = await request_container.get(on_help)
                await on_help_callable(tt_message, translator)
            return

        if cmd not in [
            tt_cmds.TT_CMD_SUBSCRIBE,
            tt_cmds.TT_CMD_UNSUBSCRIBE,
            tt_cmds.TT_CMD_ADD_ADMIN,
            tt_cmds.TT_CMD_REMOVE_ADMIN,
        ]:
            await on_unknown(tt_message, translator, connection=self.connection)
            return

        context = {
            TeamTalkMessage: tt_message,
            "args_str": args,
            NullTranslations: translator,
        }

        async with self.dishka_container(context=context) as request_container:
            # Get a fully prepared object with already injected dependencies
            handlers = await request_container.get(PrivateMessageCommandHandlers)

            # Select the desired method and call it
            if cmd == tt_cmds.TT_CMD_SUBSCRIBE:
                await handlers.on_subscribe(tt_message, translator)
            elif cmd == tt_cmds.TT_CMD_UNSUBSCRIBE:
                await handlers.on_unsubscribe(tt_message, translator)
            elif cmd == tt_cmds.TT_CMD_ADD_ADMIN:
                await handlers.on_add_admin(tt_message, translator, args)
            elif cmd == tt_cmds.TT_CMD_REMOVE_ADMIN:
                await handlers.on_remove_admin(tt_message, translator, args)
