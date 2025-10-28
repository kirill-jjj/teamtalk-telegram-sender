"""Dishka providers specific to the TeamTalk bot components."""

import asyncio
from collections.abc import AsyncGenerator, Callable
import functools
from gettext import NullTranslations
import logging

from dishka import AsyncContainer, FromDishka, Provider, Scope, provide
import pytalk

from bot.config import Settings
from bot.core.constants import INVALID_CHANNEL_ID, MSG_TEAMTALK_CONNECTION_FAILED
from bot.core.exceptions import TeamTalkConnectionError
from bot.event_bus.bus import EventBus
from bot.teamtalk_bot.cache import TeamTalkCache
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.connection_manager import TeamTalkConnectionManager
from bot.teamtalk_bot.handlers.command_bus_handlers import TeamTalkCommandHandlers
from bot.teamtalk_bot.handlers.event_bus_subscribers import TeamTalkReplyHandler
from bot.teamtalk_bot.handlers.pytalk_event_handlers import PytalkEventHandlers
from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter

logger = logging.getLogger(__name__)


def _thread_safe_dispatch(
    bot_instance: pytalk.TeamTalkBot,
    event: str,
    /,
    *args: object,
    **kwargs: object,
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
    except RuntimeError:
        logger.exception("Error in thread-safe dispatch.")


class TeamTalkProvider(Provider):
    """Provides application-scoped dependencies related to TeamTalk."""

    scope = Scope.APP

    @provide
    @staticmethod
    def get_pytalk_event_handlers(
        event_bus: FromDishka[EventBus],
        translator_factory: FromDishka[Callable[[str | None], NullTranslations]],
    ) -> PytalkEventHandlers:
        """Provides the Pytalk event handlers."""
        return PytalkEventHandlers(event_bus, translator_factory)

    @provide(provides=pytalk.TeamTalkBot)
    @staticmethod
    async def get_patched_pytalk_bot(
        settings: FromDishka[Settings],
    ) -> pytalk.TeamTalkBot:
        """Creates, configures, and patches the TeamTalkBot instance."""
        bot = pytalk.TeamTalkBot(client_name=settings.teamtalk.client_name)
        await bot._async_setup_hook()
        logger.info("Applying thread-safe patch to pytalk dispatcher.")
        bot.dispatch = functools.partial(_thread_safe_dispatch, bot)
        return bot

    @provide
    @staticmethod
    def get_connections_dict() -> dict[str, TeamTalkConnection]:
        """Provides a dictionary for active TeamTalk connections."""
        return {}

    @provide(provides=TeamTalkConnection)
    @staticmethod
    async def get_tt_connection(
        settings: FromDishka[Settings],
        pytalk_bot: FromDishka[pytalk.TeamTalkBot],
        event_bus: FromDishka[EventBus],
        connections: FromDishka[dict[str, TeamTalkConnection]],
        pytalk_event_handlers: FromDishka[PytalkEventHandlers],
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

        conn_manager = TeamTalkConnectionManager(pytalk_bot, pytalk_event_handlers)
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
    @staticmethod
    def get_pytalk_event_router(
        app_container: FromDishka[AsyncContainer],
        tt_bot: FromDishka[pytalk.TeamTalkBot],
        connections: FromDishka[dict[str, TeamTalkConnection]],
        event_bus: FromDishka[EventBus],
        translator_factory: FromDishka[Callable[[str | None], NullTranslations]],
        pytalk_event_handlers: FromDishka[PytalkEventHandlers],
    ) -> "PytalkEventRouter":
        """Provides the Pytalk event router."""
        return PytalkEventRouter(
            app_container=app_container,
            tt_bot=tt_bot,
            connections=connections,
            event_bus=event_bus,
            translator_factory=translator_factory,
            pytalk_event_handlers=pytalk_event_handlers,
        )

    @provide
    @staticmethod
    def get_teamtalk_reply_handler(
        connections: FromDishka[dict[str, TeamTalkConnection]],
    ) -> TeamTalkReplyHandler:
        """Provides the TeamTalk reply handler."""
        return TeamTalkReplyHandler(connections=connections)

    @provide
    @staticmethod
    def get_teamtalk_command_handlers(
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
