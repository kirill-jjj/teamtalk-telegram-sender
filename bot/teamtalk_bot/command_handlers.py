"""Handlers for TeamTalk private message commands."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING, Any

import pytalk
from pytalk.message import Message as TeamTalkMessage

from bot.config import Settings
from bot.constants import (
    TT_HELP_MESSAGE_PART_DELAY,
    TT_MAX_MESSAGE_BYTES,
)
from bot.core.enums import DeeplinkAction
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.moderation_service import ModerationService
from bot.teamtalk_bot.formatters import (
    _split_text_for_tt,
    format_admin_management_result,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _is_tt_admin(
    func: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Decorator to check if a TeamTalk user is the configured main admin."""

    @functools.wraps(func)
    async def wrapper(
        self: PrivateMessageCommandHandlers,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        _ = translator.gettext
        if not self.moderation_service.is_main_teamtalk_admin(
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
        await func(self, tt_message, translator, *args, **kwargs)

    return wrapper


class PrivateMessageCommandHandlers:
    """Contains handlers for commands received via TeamTalk private messages."""

    def __init__(
        self,
        settings: Settings,
        cache: CacheService,
        deeplink_service: DeeplinkService,
        moderation_service: ModerationService,
        uow: IUnitOfWork,
    ) -> None:
        """Initializes the command handlers with necessary dependencies."""
        self.settings = settings
        self.cache = cache
        self.deeplink_service = deeplink_service
        self.moderation_service = moderation_service
        self.uow = uow

    async def _reply_to_tt_message(
        self, reply_method: Callable[[str], None], text: str
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
        self, tt_message: TeamTalkMessage, translator: NullTranslations
    ) -> None:
        """Handles the subscribe command."""
        _ = translator.gettext
        if not tt_message.user or not ttstr(tt_message.user.username):
            logger.warning(
                "Subscribe command received from TT user without a username. "
                "TT User ID: %s",
                tt_message.user.id if tt_message.user else "N/A",
            )
            tt_message.reply(
                _("Your TeamTalk account must have a username to subscribe.")
            )
            return

        reply_text = await self.deeplink_service.create_tt_deeplink_reply(
            translator=translator,
            action=DeeplinkAction.SUBSCRIBE,
            ttl_seconds=self.settings.operational_parameters.deeplink_ttl_seconds,
            payload=ttstr(tt_message.user.username),
        )
        await self._reply_to_tt_message(tt_message.reply, reply_text)

    async def on_unsubscribe(
        self, tt_message: TeamTalkMessage, translator: NullTranslations
    ) -> None:
        """Handles the unsubscribe command."""
        reply_text = await self.deeplink_service.create_tt_deeplink_reply(
            translator=translator,
            action=DeeplinkAction.UNSUBSCRIBE,
            ttl_seconds=self.settings.operational_parameters.deeplink_ttl_seconds,
        )
        await self._reply_to_tt_message(tt_message.reply, reply_text)

    @_is_tt_admin
    async def on_add_admin(
        self,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        args_str: str | None,
    ) -> None:
        """Handles the add admin command."""
        await self._manage_admin_ids(
            tt_message=tt_message,
            args_str=args_str,
            translator=translator,
            is_add_action=True,
        )

    @_is_tt_admin
    async def on_remove_admin(
        self,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        args_str: str | None,
    ) -> None:
        """Handles the remove admin command."""
        await self._manage_admin_ids(
            tt_message=tt_message,
            args_str=args_str,
            translator=translator,
            is_add_action=False,
        )

    def _parse_admin_ids_args(
        self, args_string: str, translator: NullTranslations
    ) -> tuple[list[int], list[int], list[str]]:
        _ = translator.gettext
        add_ids = []
        remove_ids = []
        error_messages = []

        args = args_string.split()
        for arg in args:
            if arg.startswith("-"):
                try:
                    remove_ids.append(int(arg[1:]))
                except ValueError:
                    error_messages.append(
                        _("Invalid Telegram ID to remove: {}").format(arg[1:])
                    )
            else:
                try:
                    add_ids.append(int(arg))
                except ValueError:
                    error_messages.append(
                        _("Invalid Telegram ID to add: {}").format(arg)
                    )
        return add_ids, remove_ids, error_messages

    async def _manage_admin_ids(
        self,
        tt_message: TeamTalkMessage,
        args_str: str | None,
        translator: NullTranslations,
        *,
        is_add_action: bool,
    ) -> None:
        _ = translator.gettext
        if not args_str:
            tt_message.reply(_("Please provide Telegram IDs."))
            return

        add_ids, remove_ids, error_messages = self._parse_admin_ids_args(
            args_str, translator
        )

        result = await self.moderation_service.manage_admin_ids(
            add_ids=add_ids,
            remove_ids=remove_ids,
            is_add_action=is_add_action,
            error_messages=error_messages,
        )

        response_message = format_admin_management_result(result, translator)
        await self._reply_to_tt_message(tt_message.reply, response_message)
