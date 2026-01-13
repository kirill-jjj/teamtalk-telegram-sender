"""Database-related Dishka providers for dependency injection."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.config import Settings
from bot.database.engine import (
    AsyncSessionFactoryType,
    create_engine,
    create_session_factory,
)
from bot.database.uow import IUnitOfWork, SqlModelUnitOfWork


class DatabaseProvider(Provider):
    """Provides database-related dependencies."""

    scope = Scope.APP

    @provide(scope=Scope.APP)
    @staticmethod
    def get_engine(settings: Settings) -> AsyncEngine:
        """Provides the database engine."""
        return create_engine(settings)

    @provide(scope=Scope.APP)
    @staticmethod
    def get_session_factory(engine: AsyncEngine) -> AsyncSessionFactoryType:
        """Provides the database session factory."""
        return create_session_factory(engine)

    @provide(scope=Scope.REQUEST)
    @staticmethod
    def get_uow(
        factory: AsyncSessionFactoryType,
    ) -> IUnitOfWork:
        """Provides the Unit of Work."""
        return SqlModelUnitOfWork(
            session_factory=factory,
        )
