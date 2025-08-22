"""Handlers for TeamTalk private message commands."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import functools
from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING, Any, TypedDict

from pydantic import BaseModel, Field, model_validator
import pytalk
from pytalk.message import Message as TeamTalkMessage

from bot.config import Settings
from bot.constants import (
    TT_HELP_MESSAGE_PART_DELAY,
    TT_MAX_MESSAGE_BYTES,
)
from bot.core.enums import DeeplinkAction
from bot.database.uow import IUnitOfWork
from bot.event_bus.bus import EventBus
from bot.models import Admin
from bot.services.cache_service import CacheService
from bot.teamtalk_bot import command_constants as tt_cmds
from bot.teamtalk_bot.events import AdminStatusChangedEvent

if TYPE_CHECKING:
    pass

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


class _AdminIdArgs(BaseModel):
    """Parses and validates arguments for admin commands that take Telegram IDs."""

    valid_ids: list[int] = Field(default_factory=list)
    invalid_entries: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def parse_str_to_dict(cls, data: str | None) -> dict[str, list[int] | list[str]]:
        """Parse a string of space-separated args into valid IDs and invalid entries."""
        if not isinstance(data, str) or not (command_args_str := data.strip()):
            return {"valid_ids": [], "invalid_entries": []}
        valid_ids = []
        invalid_entries = []
        for part in command_args_str.split():
            if part.isdigit():
                valid_ids.append(int(part))
            else:
                invalid_entries.append(part)
        return {"valid_ids": valid_ids, "invalid_entries": invalid_entries}


def _is_tt_admin(
    func: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    """Decorator to check if a TeamTalk user is the configured main admin."""

    @functools.wraps(func)
    async def wrapper(
        self: PrivateMessageCommandHandlers,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
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


async def _reply_with_deeplink(
    tt_message: TeamTalkMessage,
    uow: IUnitOfWork,
    translator: NullTranslations,
    action: DeeplinkAction,
    reply_text_source: str,
    settings: Settings,
    cache: CacheService,
    payload: str | None = None,
) -> None:
    """Generates a deeplink and replies to the user with it."""
    _ = translator.gettext
    deeplink = await uow.deeplinks.create(
        action,
        settings.operational_parameters.deeplink_ttl_seconds,
        payload=payload,
    )
    bot_username = cache.get_bot_username()
    if not bot_username:
        logger.error("Bot username not found in cache. Cannot create deeplink.")
        tt_message.reply(
            _("Could not generate a link, bot username is not configured.")
        )
        return
    deeplink_url = f"https://t.me/{bot_username}?start={deeplink.token}"
    logger.info(
        "Generated deeplink %s for TT user %s",
        deeplink.token,
        ttstr(tt_message.user.username),
    )
    tt_message.reply(_(reply_text_source).format(deeplink_url=deeplink_url))


class _DeeplinkConfig(TypedDict):
    """Configuration for a deeplink action."""

    get_payload: Callable[[TeamTalkMessage], str | None]
    reply_text_key: str


DEEPLINK_CONFIG: dict[DeeplinkAction, _DeeplinkConfig] = {
    DeeplinkAction.SUBSCRIBE: {
        "get_payload": lambda msg: ttstr(msg.user.username),
        "reply_text_key": (
            "Click this link to subscribe to notifications "
            "(link valid for 5 minutes):\n{deeplink_url}"
        ),
    },
    DeeplinkAction.UNSUBSCRIBE: {
        "get_payload": lambda _: None,
        "reply_text_key": (
            "Click this link to unsubscribe from notifications "
            "(link valid for 5 minutes):\n{deeplink_url}"
        ),
    },
}


async def _handle_deeplink_command(
    tt_message: TeamTalkMessage,
    uow: IUnitOfWork,
    translator: NullTranslations,
    settings: Settings,
    cache: CacheService,
    action: DeeplinkAction,
) -> None:
    """Generic handler for subscribe/unsubscribe commands."""
    _ = translator.gettext
    config = DEEPLINK_CONFIG[action]
    payload = config["get_payload"](tt_message)
    reply_text_source = _(config["reply_text_key"])

    await _reply_with_deeplink(
        tt_message=tt_message,
        uow=uow,
        translator=translator,
        action=action,
        payload=payload,
        reply_text_source=reply_text_source,
        settings=settings,
        cache=cache,
    )


class PrivateMessageCommandHandlers:
    """Contains handlers for commands received via TeamTalk private messages."""

    def __init__(
        self,
        uow: IUnitOfWork,
        settings: Settings,
        cache: CacheService,
        event_bus: EventBus,
    ) -> None:
        """Initializes the command handlers with necessary dependencies."""
        self.uow = uow
        self.settings = settings
        self.cache = cache
        self.event_bus = event_bus

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

        await _handle_deeplink_command(
            tt_message,
            self.uow,
            translator,
            self.settings,
            self.cache,
            DeeplinkAction.SUBSCRIBE,
        )

    async def on_unsubscribe(
        self, tt_message: TeamTalkMessage, translator: NullTranslations
    ) -> None:
        """Handles the unsubscribe command."""
        await _handle_deeplink_command(
            tt_message,
            self.uow,
            translator,
            self.settings,
            self.cache,
            DeeplinkAction.UNSUBSCRIBE,
        )

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

    async def _manage_admin_ids(
        self,
        tt_message: TeamTalkMessage,
        args_str: str | None,
        translator: NullTranslations,
        *,
        is_add_action: bool,
    ) -> None:
        _ = translator.gettext
        args = _AdminIdArgs.model_validate(args_str)

        if not args.valid_ids and not args.invalid_entries:
            prompt_msg_key = (
                _("Please provide Telegram IDs. Example: {cmd} 12345678").format(
                    cmd=tt_cmds.TT_CMD_ADD_ADMIN
                )
                if is_add_action
                else _("Please provide Telegram IDs. Example: {cmd} 12345678").format(
                    cmd=tt_cmds.TT_CMD_REMOVE_ADMIN
                )
            )
            tt_message.reply(prompt_msg_key)
            return

        success_count = 0
        failed_action_ids = []

        for telegram_id in args.valid_ids:
            try:
                admin = await self.uow.admins.get_by_id(telegram_id)
                if (is_add_action and not admin) or (not is_add_action and admin):
                    if is_add_action:
                        await self.uow.admins.add(Admin(telegram_id=telegram_id))
                    elif admin:
                        await self.uow.admins.delete(admin)

                if is_add_action:
                    self.cache.add_admin(telegram_id)
                else:
                    self.cache.remove_admin(telegram_id)

                user_settings = await self.uow.users.get_or_create(
                    telegram_id, {"language_code": self.settings.general.default_lang}
                )
                await self.event_bus.publish(
                    AdminStatusChangedEvent(
                        telegram_id=telegram_id,
                        is_admin=is_add_action,
                        lang_code=user_settings.language_code,
                    )
                )
                success_count += 1
            except Exception:
                failed_action_ids.append(telegram_id)
                action_str = "add" if is_add_action else "remove"
                logger.exception("Failed to %s admin %s", action_str, telegram_id)

        report = self._create_admin_action_report(
            translator,
            success_count,
            failed_action_ids,
            args.invalid_entries,
            is_add_action=is_add_action,
        )
        tt_message.reply(report)

    def _create_admin_action_report(
        self,
        translator: NullTranslations,
        success_count: int,
        failed_ids: list[int],
        invalid_entries: list[str],
        *,
        is_add_action: bool,
    ) -> str:
        _ = translator.gettext

        if is_add_action:
            s_msg = "Successfully added {count} admin."
            p_msg = "Successfully added {count} admins."
            error_msg_key = _("ID {telegram_id} is already an admin or failed to add.")
        else:
            s_msg = "Successfully removed {count} admin."
            p_msg = "Successfully removed {count} admins."
            error_msg_key = _(
                "Admin with ID {telegram_id} not found or failed to remove."
            )

        success_message = translator.ngettext(s_msg, p_msg, success_count).format(
            count=success_count
        )

        reply_parts = []
        if success_count > 0:
            reply_parts.append(success_message)

        invalid_id_msg_key = _("'{telegram_id_str}' is not a valid numeric ID.")
        errors = [
            error_msg_key.format(telegram_id=failed_id) for failed_id in failed_ids
        ]
        errors.extend(
            [
                invalid_id_msg_key.format(telegram_id_str=invalid_entry)
                for invalid_entry in invalid_entries
            ]
        )

        if errors:
            header = _("Action Results:")
            error_list_str = "\n".join(f"- {error}" for error in errors)
            reply_parts.append(f"{header}\n{error_list_str}")

        if not reply_parts:
            return str(_("No action was performed. Please check the IDs provided."))

        return "\n\n".join(reply_parts)
