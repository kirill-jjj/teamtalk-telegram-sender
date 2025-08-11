"""Dishka providers for TeamTalk bot components."""
from dishka import AsyncContainer, FromDishka, Provider, Scope, provide

from bot.teamtalk_bot.command_router import CommandRouter
from bot.teamtalk_bot.connection import TeamTalkConnection


class TeamTalkProvider(Provider):
    """Provides dependencies for the TeamTalk bot command handlers."""

    scope = Scope.REQUEST

    @provide
    def get_command_router(
        self,
        dishka_container: FromDishka[AsyncContainer],
        connection: FromDishka[TeamTalkConnection],
    ) -> CommandRouter:
        """Provides the CommandRouter."""
        return CommandRouter(
            dishka_container=dishka_container,
            connection=connection,
        )
