"""Command router for TeamTalk bot."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from gettext import GNUTranslations, NullTranslations
import logging
from typing import TYPE_CHECKING, Any

from bot.config import Settings
from bot.database.engine import AsyncSessionFactoryType
from bot.database.repositories.admin_repository import AdminRepository
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.services.cache_service import CacheService
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
        self.handlers: dict[str, Callable[..., Awaitable[None]]] = {
            tt_cmds.TT_CMD_SUBSCRIBE: on_subscribe,
            tt_cmds.TT_CMD_UNSUBSCRIBE: on_unsubscribe,
            tt_cmds.TT_CMD_ADD_ADMIN: on_add_admin,  # type: ignore[dict-item]
            tt_cmds.TT_CMD_REMOVE_ADMIN: on_remove_admin,  # type: ignore[dict-item]
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
        if not handler:
            await on_unknown(tt_message, translator, connection=self.connection)
            return

        # Create all possible dependencies once
        user_repo = UserRepository()
        user_repo._session = session
        admin_repo = AdminRepository()
        admin_repo._session = session
        deeplink_repo = DeeplinkRepository()
        deeplink_repo._session = session
        ban_repo = BanRepository()
        ban_repo._session = session
        subscriber_repo = SubscriberRepository()
        subscriber_repo._session = session

        # Pool of all available dependencies
        dependencies_pool: dict[str, Any] = {
            "tt_message": tt_message,
            "translator": translator,
            "settings": self.settings,
            "cache": self.cache,
            "bot": self.bot,
            "user_repo": user_repo,
            "admin_repo": admin_repo,
            "deeplink_repo": deeplink_repo,
            "ban_repo": ban_repo,
            "subscriber_repo": subscriber_repo,
            "args_str": args,
        }

        # Определяем, какие зависимости нужны каждому обработчику
        handler_dependencies: dict[Callable[..., Any], list[str]] = {
            on_subscribe: [
                "tt_message",
                "deeplink_repo",
                "translator",
                "settings",
                "bot",
            ],
            on_unsubscribe: [
                "tt_message",
                "deeplink_repo",
                "translator",
                "settings",
                "bot",
            ],
            on_add_admin: [
                "tt_message",
                "translator",
                "settings",
                "cache",
                "bot",
                "admin_repo",
                "user_repo",
                "args_str",
            ],
            on_remove_admin: [
                "tt_message",
                "translator",
                "settings",
                "cache",
                "bot",
                "admin_repo",
                "user_repo",
                "args_str",
            ],
            on_help: ["tt_message", "translator", "settings"],
        }

        required_deps_names = handler_dependencies.get(handler)

        if required_deps_names:
            # Collect kwargs only with the necessary dependencies
            kwargs_for_handler = {
                dep: dependencies_pool[dep] for dep in required_deps_names
            }
            await handler(**kwargs_for_handler)
        else:
            logger.error(
                    "Handler for command '%s' found but its dependencies are not "
                    "defined in command_router.",
                cmd,
            )
