"""Dishka providers specific to the TeamTalk bot components."""

from collections.abc import AsyncGenerator, Callable
from gettext import NullTranslations
import logging

from dishka import AsyncContainer, FromDishka, Provider, Scope, provide
import pytalk

from bot.command_handlers.teamtalk_handlers import TeamTalkCommandHandlers
from bot.config import Settings
from bot.constants import INVALID_CHANNEL_ID, MSG_TEAMTALK_CONNECTION_FAILED
from bot.core.exceptions import TeamTalkConnectionError
from bot.event_bus.bus import EventBus
from bot.event_handlers.teamtalk_replier import TeamTalkReplyHandler
from bot.services.report_service import ReportService
from bot.teamtalk_bot.cache import TeamTalkCache
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.connection_manager import TeamTalkConnectionManager
from bot.teamtalk_bot.pytalk_event_router import PytalkEventRouter


class TeamTalkProvider(Provider):
    """Provides application-scoped dependencies related to TeamTalk."""

    scope = Scope.APP

    @provide
    def get_teamtalk_bot(self, settings: FromDishka[Settings]) -> pytalk.TeamTalkBot:
        """Provides the TeamTalk bot instance."""
        return pytalk.TeamTalkBot(client_name=settings.teamtalk.client_name)

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
    ) -> AsyncGenerator[TeamTalkConnection, None]:
        """Provider for TeamTalkConnection with managed lifecycle."""
        await pytalk_bot._async_setup_hook()
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

        def _raise_connection_error() -> None:
            raise TeamTalkConnectionError(MSG_TEAMTALK_CONNECTION_FAILED)

        try:
            if not await connection.connect():
                _raise_connection_error()
            yield connection
        except Exception as e:
            logging.getLogger(__name__).exception(
                "Failed to establish TeamTalk connection. Bot will run without it."
            )
            raise TeamTalkConnectionError("Failed to establish TeamTalk connection") from e

        await connection.disconnect_instance()

    @provide
    def get_pytalk_event_router(
        self,
        app_container: FromDishka[AsyncContainer],
        tt_bot: FromDishka[pytalk.TeamTalkBot],
        connections: FromDishka[dict[str, TeamTalkConnection]],
        event_bus: FromDishka[EventBus],
        translator_factory: FromDishka[Callable[[str], NullTranslations]],
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
    def get_report_service(self, settings: FromDishka[Settings]) -> ReportService:
        """Provides a ReportService."""
        return ReportService(settings=settings)

    @provide
    def get_teamtalk_command_handlers(
        self,
        tt_connection: FromDishka[TeamTalkConnection],
        translator_factory: FromDishka[Callable[[str], NullTranslations]],
        report_service: FromDishka[ReportService],
    ) -> TeamTalkCommandHandlers:
        """Provides the TeamTalk command handlers if a connection is available."""
        return TeamTalkCommandHandlers(
            tt_connection=tt_connection,
            translator_factory=translator_factory,
            report_service=report_service,
        )
