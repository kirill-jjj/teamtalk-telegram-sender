"""Handlers for TeamTalk private message commands."""

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
from bot.core.enums import DeeplinkAction

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from gettext import NullTranslations

    from pytalk.message import Message as TeamTalkMessage

    from bot.config import Settings
    from bot.database.uow import IUnitOfWork
    from bot.services.cache_service import CacheService
    from bot.services.deeplink_service import DeeplinkService
    from bot.services.moderation_service import ModerationService

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _split_text_for_tt(text: str, max_len_bytes: int) -> list[str]:
    """Splits a long text message into parts suitable for TeamTalk."""
    parts_to_send_list = []
    remaining_text = text

    while remaining_text:
        if len(remaining_text.encode("utf-8", errors="ignore")) <= max_len_bytes:
            parts_to_send_list.append(remaining_text)
            break

        current_chunk_str = ""
        current_chunk_bytes_len = 0
        last_safe_split_index_in_chunk = -1
        last_safe_split_index_in_remaining = -1

        for i, char_code in enumerate(remaining_text):
            char_bytes = char_code.encode("utf-8", errors="ignore")
            char_bytes_len = len(char_bytes)

            if current_chunk_bytes_len + char_bytes_len > max_len_bytes:
                if last_safe_split_index_in_chunk != -1:
                    parts_to_send_list.append(
                        current_chunk_str[:last_safe_split_index_in_chunk]
                    )
                    remaining_text = remaining_text[
                        last_safe_split_index_in_remaining:
                    ].lstrip()
                else:
                    parts_to_send_list.append(current_chunk_str)
                    remaining_text = remaining_text[i:].lstrip()
                break

            current_chunk_str += char_code
            current_chunk_bytes_len += char_bytes_len

            if char_code in ("\n", " "):
                last_safe_split_index_in_chunk = len(current_chunk_str)
                last_safe_split_index_in_remaining = i + 1

            if i == len(remaining_text) - 1:
                parts_to_send_list.append(current_chunk_str)
                remaining_text = ""
                break
        else:
            if current_chunk_str and not remaining_text:
                pass
            remaining_text = ""
    return parts_to_send_list


async def _send_long_tt_reply(
    reply_method: Callable[[str], None],
    text: str,
    max_len_bytes: int = TT_MAX_MESSAGE_BYTES,
) -> None:
    """Splits a long text message into parts suitable for TeamTalk and sends them."""
    if not text:
        return

    parts_to_send_list = await asyncio.to_thread(
        _split_text_for_tt, text, max_len_bytes
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
                logger.exception("Error sending part %s of TT message.", part_idx + 1)
                break


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
        if (
            not self.settings.general.admin_username
            or ttstr(tt_message.user.username) != self.settings.general.admin_username
        ):
            logger.warning(
                "Unauthorized admin command by TT user %s for %s.",
                ttstr(tt_message.user.username),
                func.__name__,
            )
            tt_message.reply(_("You are not authorized to perform this action."))
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
        tt_message.reply(reply_text)

    async def on_unsubscribe(
        self, tt_message: TeamTalkMessage, translator: NullTranslations
    ) -> None:
        """Handles the unsubscribe command."""
        reply_text = await self.deeplink_service.create_tt_deeplink_reply(
            translator=translator,
            action=DeeplinkAction.UNSUBSCRIBE,
            ttl_seconds=self.settings.operational_parameters.deeplink_ttl_seconds,
        )
        tt_message.reply(reply_text)

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

        response_message = await self.moderation_service.manage_admin_ids(
            add_ids=add_ids,
            remove_ids=remove_ids,
            is_add_action=is_add_action,
            error_messages=error_messages,
            translator=translator,
        )
        tt_message.reply(response_message)
