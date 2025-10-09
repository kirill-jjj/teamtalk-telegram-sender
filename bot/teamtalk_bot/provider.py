"""Dishka providers specific to the TeamTalk bot components."""

import asyncio
from collections.abc import AsyncGenerator, Callable
import functools
from gettext import NullTranslations
import logging
from typing import Any

from dishka import AsyncContainer, FromDishka, Provider, Scope, provide
import pytalk

from bot.command_handlers.teamtalk_handlers import TeamTalkCommandHandlers
from bot.config import Settings
from bot.constants import INVALID_CHANNEL_ID, MSG_TEAMTALK_CONNECTION_FAILED
from bot.core.exceptions import TeamTalkConnectionError
from bot.database.uow import IUnitOfWork
from bot.event_bus.bus import EventBus
from bot.event_handlers.teamtalk_replier import TeamTalkReplyHandler
from bot.services.report_service import ReportService
from bot.teamtalk_bot.cache import TeamTalkCache
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.connection_manager import TeamTalkConnectionManager
from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter
from bot.telegram_bot.types.bots import EventBot

logger = logging.getLogger(__name__)


def _thread_safe_dispatch(
    bot_instance: pytalk.TeamTalkBot,
    event: str,
    /,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Thread-safe version of the dispatch method for pytalk.

    Uses call_soon_threadsafe to call _schedule_event in the main asyncio loop.
    """
    try:
        coro = getattr(bot_instance, "on_" + event)
        bot_instance.loop.call_soon_threadsafe(
            bot_instance._schedule_event, coro, "on_" + event, *args, **kwargs
        )
    except AttributeError:
        pass  # Ignore events without handlers
    except Exception:
        logger.exception("Error in thread-safe dispatch.")


class TeamTalkProvider(Provider):
    """Provides application-scoped dependencies related to TeamTalk."""

    scope = Scope.APP

    @provide(provides=pytalk.TeamTalkBot)
    async def get_patched_pytalk_bot(
        self, settings: FromDishka[Settings]
    ) -> pytalk.TeamTalkBot:
        """Creates, configures, and patches the TeamTalkBot instance."""
        bot = pytalk.TeamTalkBot(client_name=settings.teamtalk.client_name)
        await bot._async_setup_hook()
        logger.info("Applying thread-safe patch to pytalk dispatcher.")
        bot.dispatch = functools.partial(_thread_safe_dispatch, bot)
        return bot

    @provide
    def get_connections_dict(self) -> dict[str, TeamTalkConnection]:
        """Provides a dictionary for active TeamTalk connections."""
        return {}

    @provide(provides=TeamTalkConnection)
    async def get_tt_connection(
        self,
        settings: FromDishka[Settings],
        pytalk_bot: FromDishka[pytalk.TeamTalkBot],
        event_bus: FromDishka[EventBus],
        connections: FromDishka[dict[str, TeamTalkConnection]],
        _router: FromDishka[PytalkEventRouter],  # Add _router dependency back
    ) -> AsyncGenerator[TeamTalkConnection, None]:
        """Provider for TeamTalkConnection with managed lifecycle."""
        tt_config = settings.teamtalk
        server_info = pytalk.TeamTalkServerInfo(
            host=tt_config.host_name,
            tcp_port=tt_config.port,
            udp_port=tt_config.port,
            username=tt_config.user_name,
            password=tt_config.password,
            encrypted=tt_config.encrypted,
            nickname=settings.teamtalk.nick_name,
            join_channel_id=int(tt_config.channel)
            if tt_config.channel.isdigit()
            else INVALID_CHANNEL_ID,
            join_channel_password=tt_config.channel_password or "",
        )

        conn_manager = TeamTalkConnectionManager(pytalk_bot)
        cache_manager = TeamTalkCache(settings)

        connection = TeamTalkConnection(
            server_info=server_info,
            settings=settings,
            event_bus=event_bus,
            connection_manager=conn_manager,
            cache_manager=cache_manager,
        )

        server_key = f"{server_info.host}:{server_info.tcp_port}"
        connections[server_key] = connection

        try:
            # 2. Execute the blocking connection in a separate thread
            is_connected = await asyncio.to_thread(connection.connect)
            if not is_connected:
                raise TeamTalkConnectionError(MSG_TEAMTALK_CONNECTION_FAILED)

            # 3. Pass the ready and connected connection to the application
            yield connection

        finally:
            # 4. Disconnect gracefully on exit
            logging.getLogger(__name__).info("Disconnecting from TeamTalk server...")
            if connection.instance:
                await connection.disconnect_instance()

    @provide
    def get_pytalk_event_router(
        self,
        app_container: FromDishka[AsyncContainer],
        tt_bot: FromDishka[pytalk.TeamTalkBot],
        connections: FromDishka[dict[str, TeamTalkConnection]],
        event_bus: FromDishka[EventBus],
        translator_factory: FromDishka[Callable[[str | None], NullTranslations]],
    ) -> "PytalkEventRouter":
        """Provides the Pytalk event router."""
        return PytalkEventRouter(
            app_container=app_container,
            tt_bot=tt_bot,
            connections=connections,
            event_bus=event_bus,
            translator_factory=translator_factory,
        )

    @provide
    def get_teamtalk_reply_handler(
        self,
        connections: FromDishka[dict[str, TeamTalkConnection]],
    ) -> TeamTalkReplyHandler:
        """Provides the TeamTalk reply handler."""
        return TeamTalkReplyHandler(connections=connections)

    @provide
    def get_report_service(
        self,
        settings: FromDishka[Settings],
        uow: FromDishka[IUnitOfWork],
        bot: FromDishka[EventBot],
    ) -> ReportService:
        """Provides a ReportService."""
        return ReportService(
            settings=settings,
            uow=uow,
            bot=bot,
        )

    @provide
    def get_teamtalk_command_handlers(
        self,
        tt_connection: FromDishka[TeamTalkConnection],
        translator_factory: FromDishka[Callable[[str | None], NullTranslations]],
        settings: FromDishka[Settings],
    ) -> TeamTalkCommandHandlers:
        """Provides the TeamTalk command handlers if a connection is available."""
        return TeamTalkCommandHandlers(
            tt_connection=tt_connection,
            translator_factory=translator_factory,
            settings=settings,
        )
