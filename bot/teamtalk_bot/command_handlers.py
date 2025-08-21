"""Handlers for TeamTalk private message commands."""

from __future__ import annotations

from gettext import NullTranslations
from typing import TYPE_CHECKING

from dishka import FromDishka
from pytalk.message import Message as TeamTalkMessage

from bot.config import Settings
from bot.core.enums import DeeplinkAction
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.teamtalk_bot.commands import (
    _handle_deeplink_command,
    _manage_admin_ids,
)

if TYPE_CHECKING:
    from bot.event_bus.bus import EventBus
    from bot.teamtalk_bot import command_constants as tt_cmds


class PrivateMessageCommandHandlers:
    """Contains handlers for commands received via TeamTalk private messages."""

    def __init__(
        self,
        uow: FromDishka[IUnitOfWork],
        settings: FromDishka[Settings],
        cache: FromDishka[CacheService],
        event_bus: FromDishka[EventBus],
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
        async with self.uow:
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
        async with self.uow:
            await _handle_deeplink_command(
                tt_message,
                self.uow,
                translator,
                self.settings,
                self.cache,
                DeeplinkAction.UNSUBSCRIBE,
            )

    async def on_add_admin(
        self,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        args_str: str | None,
    ) -> None:
        """Handles the add admin command."""
        _ = translator.gettext
        await _manage_admin_ids(
            tt_message=tt_message,
            args_str=args_str,
            translator=translator,
            repo_action=self.uow.admins.add,
            is_add_action=True,
            prompt_msg_key=_(
                "Please provide Telegram IDs. Example: {cmd} 12345678"
            ).format(
                cmd=tt_cmds.TT_CMD_ADD_ADMIN
            ),
            error_msg_key=_("ID {telegram_id} is already an admin or failed to add."),
            invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric ID."),
            header_msg_key=_("Action Results:"),
            settings=self.settings,
            cache=self.cache,
            event_bus=self.event_bus,
            admin_repo=self.uow.admins,
            user_repo=self.uow.users,
        )

    async def on_remove_admin(
        self,
        tt_message: TeamTalkMessage,
        translator: NullTranslations,
        args_str: str | None,
    ) -> None:
        """Handles the remove admin command."""
        _ = translator.gettext
        await _manage_admin_ids(
            tt_message=tt_message,
            args_str=args_str,
            translator=translator,
            repo_action=self.uow.admins.delete,
            is_add_action=False,
            prompt_msg_key=_(
                "Please provide Telegram IDs. Example: {cmd} 12345678"
            ).format(
                cmd=tt_cmds.TT_CMD_REMOVE_ADMIN
            ),
            error_msg_key=(
                _("Admin with ID {telegram_id} not found or failed to remove.")
            ),
            invalid_id_msg_key=_("'{telegram_id_str}' is not a valid numeric ID."),
            header_msg_key=_("Action Results:"),
            settings=self.settings,
            cache=self.cache,
            event_bus=self.event_bus,
            admin_repo=self.uow.admins,
            user_repo=self.uow.users,
        )
