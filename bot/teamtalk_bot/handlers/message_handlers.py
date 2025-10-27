"""Handlers for TeamTalk private message commands and command routing."""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import TYPE_CHECKING, Any

import pytalk

from bot.constants import (
    TT_HELP_MESSAGE_PART_DELAY,
    TT_MAX_MESSAGE_BYTES,
)
from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.formatters import (
    _split_text_for_tt,
    format_admin_management_result,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from gettext import NullTranslations

    from pytalk.message import Message as TeamTalkMessage

    from bot.database.uow import IUnitOfWork
    from bot.services.teamtalk_command_service import TeamTalkCommandService


logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _is_tt_admin(
    func: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Decorator to check if a TeamTalk user is the configured main admin."""

    @functools.wraps(func)
    async def wrapper(
        self: PrivateMessageCommandHandlers,
        uow: IUnitOfWork,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        _ = translator.gettext
        if not self.tt_command_service.admin_service.is_main_teamtalk_admin(
            ttstr(tt_message.user.username)
        ):
            logger.warning(
                "Unauthorized admin command by TT user %s for %s.",
                ttstr(tt_message.user.username),
                func.__name__,
            )
            await self._reply_to_tt_message(
                tt_message.reply, _("You are not authorized to perform this action.")
            )
            return
        await func(self, uow, tt_message, translator, *args, **kwargs)

    return wrapper


class PrivateMessageCommandHandlers:
    """Contains handlers for commands received via TeamTalk private messages."""

    def __init__(self, tt_command_service: TeamTalkCommandService) -> None:
        """Initializes the command handlers with necessary dependencies."""
        self.tt_command_service = tt_command_service

    @staticmethod
    async def _reply_to_tt_message(
        reply_method: Callable[[str], None], text: str
    ) -> None:
        """Splits a long text message into parts for TeamTalk and sends them."""
        if not text:
            return

        parts_to_send_list = await asyncio.to_thread(
            _split_text_for_tt, text, TT_MAX_MESSAGE_BYTES
        )

        for part_idx, part_to_send_str in enumerate(parts_to_send_list):
            if part_to_send_str.strip():
                try:
                    reply_method(part_to_send_str)
                    encoded_len = len(part_to_send_str.encode("utf-8", errors="ignore"))
                    logger.debug(
                        "Sent part %s/%s of TT message, length %s bytes.",
                        part_idx + 1,
                        len(parts_to_send_list),
                        encoded_len,
                    )
                    if part_idx < len(parts_to_send_list) - 1:
                        await asyncio.sleep(TT_HELP_MESSAGE_PART_DELAY)
                except pytalk.exceptions.TeamTalkException:
                    logger.exception(
                        "Error sending part %s of TT message.", part_idx + 1
                    )
                    break

    async def on_subscribe(
        self,
        uow: IUnitOfWork,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
    ) -> None:
        """Handles the subscribe command."""
        _ = translator.gettext
        if not tt_message.user or not ttstr(tt_message.user.username):
            logger.warning(
                "Subscribe command received from TT user without a username. "
                "TT User ID: %s",
                tt_message.user.id if tt_message.user else "N/A",
            )
            await self._reply_to_tt_message(
                tt_message.reply,
                _("Your TeamTalk account must have a username to subscribe."),
            )
            return

        reply_text = await self.tt_command_service.handle_subscribe(
            uow, ttstr(tt_message.user.username), translator
        )
        await self._reply_to_tt_message(tt_message.reply, reply_text)

    async def on_unsubscribe(
        self,
        uow: IUnitOfWork,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
    ) -> None:
        """Handles the unsubscribe command."""
        reply_text = await self.tt_command_service.handle_unsubscribe(uow, translator)
        await self._reply_to_tt_message(tt_message.reply, reply_text)

    @_is_tt_admin
    async def on_add_admin(
        self,
        uow: IUnitOfWork,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        args_str: str | None,
    ) -> None:
        """Handles the add admin command."""
        await self._update_admins(
            uow=uow,
            tt_message=tt_message,
            args_str=args_str,
            translator=translator,
            is_add_action=True,
        )

    @_is_tt_admin
    async def on_remove_admin(
        self,
        uow: IUnitOfWork,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        args_str: str | None,
    ) -> None:
        """Handles the remove admin command."""
        await self._update_admins(
            uow=uow,
            tt_message=tt_message,
            args_str=args_str,
            translator=translator,
            is_add_action=False,
        )

    async def _update_admins(
        self,
        uow: IUnitOfWork,
        tt_message: TeamTalkMessage,
        args_str: str | None,
        translator: NullTranslations,
        *,
        is_add_action: bool,
    ) -> None:
        result = await self.tt_command_service.handle_admin_update(
            uow,
            args_str=args_str,
            translator=translator,
            is_add_action=is_add_action,
        )

        response_message = format_admin_management_result(result, translator)
        await self._reply_to_tt_message(tt_message.reply, response_message)


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
