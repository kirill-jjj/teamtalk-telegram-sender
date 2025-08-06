"""Command router for TeamTalk bot."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from gettext import GNUTranslations, NullTranslations
import logging
from typing import TYPE_CHECKING, cast

from bot.config import Settings
from bot.database.engine import AsyncSessionFactoryType
from bot.database.repositories.admin_repository import AdminRepository
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.subscription_service import SubscriptionService
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
    from aiogram import Bot
    from pytalk.message import Message as TeamTalkMessage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bot.teamtalk_bot.connection import TeamTalkConnection


logger = logging.getLogger(__name__)


class CommandRouter:
    """Maps commands to their handlers and executes them."""

    def __init__(
        self,
        settings: Settings,
        session_factory: AsyncSessionFactoryType,
        cache: CacheService,
        translator_factory: Callable[[str], GNUTranslations | NullTranslations],
        connection: TeamTalkConnection,
        bot: Bot,
    ) -> None:
        """Initializes the command router."""
        self.settings = settings
        self.session_factory = session_factory
        self.cache = cache
        self.translator_factory = translator_factory
        self.connection = connection
        self.bot = bot
        self.handlers = {
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
        session: AsyncSession,
    ) -> None:
        """Routes a command to the appropriate handler."""
        handler = self.handlers.get(cmd)
        if handler:
            # Manually create dependencies for the TT bot command handlers
            user_repo = UserRepository(session)
            ban_repo = BanRepository(session)
            admin_repo = AdminRepository(session)
            subscriber_repo = SubscriberRepository(session)
            deeplink_repo = DeeplinkRepository(session)
            subscription_service = SubscriptionService(
                user_repo, subscriber_repo, ban_repo, self.cache
            )
            deeplink_service = DeeplinkService(
                subscription_service, ban_repo, admin_repo, self.cache
            )

            handler_type = Callable[..., Awaitable[None]]
            typed_handler = cast(handler_type, handler)

            kwargs = {
                "tt_message": tt_message,
                "translator": translator,
                "settings": self.settings,
                "cache": self.cache,
                "bot": self.bot,
                "user_repo": user_repo,
                "admin_repo": admin_repo,
                "deeplink_repo": deeplink_repo,
            }
            if cmd in [tt_cmds.TT_CMD_ADD_ADMIN, tt_cmds.TT_CMD_REMOVE_ADMIN]:
                kwargs["args_str"] = args

            await typed_handler(**kwargs)
        else:
            await on_unknown(tt_message, translator, connection=self.connection)
