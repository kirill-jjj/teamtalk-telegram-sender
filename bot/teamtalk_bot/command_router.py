"""Command router for TeamTalk bot."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from gettext import NullTranslations
import inspect
import logging
from typing import TYPE_CHECKING, Any

from dishka import AsyncContainer
from pytalk.message import Message as TeamTalkMessage

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
        self.handlers: dict[str, Callable[..., Awaitable[Any | None]]] = {
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
        translator: NullTranslations,
    ) -> None:
        """Routes a command to the appropriate handler."""
        handler = self.handlers.get(cmd)
        if not handler:
            await on_unknown(tt_message, translator, connection=self.connection)
            return

        async with (await self.dishka_container())(
            context={
                TeamTalkMessage: tt_message,
                "args_str": args,
                NullTranslations: translator,
            }
        ) as request_container:
            handler_kwargs = {
                "tt_message": tt_message,
                "translator": translator,
                "dishka_container": request_container,
            }

            # Check if handler expects 'args_str'
            if "args_str" in inspect.signature(handler).parameters:
                handler_kwargs["args_str"] = args

            await handler(**handler_kwargs)
