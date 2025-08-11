"""Unit of Work pattern for managing database transactions."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.engine import AsyncSessionFactoryType
from bot.database.repositories.admin_repository import AdminRepository
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository


class IUnitOfWork(ABC):
    """Abstract base class for the Unit of Work pattern."""

    users: UserRepository
    bans: BanRepository
    admins: AdminRepository
    subscribers: SubscriberRepository
    deeplinks: DeeplinkRepository

    @abstractmethod
    async def __aenter__(self) -> Self:
        """Enter the context manager, starting a transaction."""
        raise NotImplementedError

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the context manager, committing or rolling back the transaction."""
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        """Commit the changes within the current transaction."""
        raise NotImplementedError

    @abstractmethod
    async def rollback(self) -> None:
        """Roll back the changes within the current transaction."""
        raise NotImplementedError


class SqlModelUnitOfWork(IUnitOfWork):
    """A SQLModel implementation of the Unit of Work pattern."""

    def __init__(
        self,
        session_factory: AsyncSessionFactoryType,
        users: UserRepository,
        bans: BanRepository,
        admins: AdminRepository,
        subscribers: SubscriberRepository,
        deeplinks: DeeplinkRepository,
    ) -> None:
        """Initializes the Unit of Work and its repositories."""
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

        self.users = users
        self.bans = bans
        self.admins = admins
        self.subscribers = subscribers
        self.deeplinks = deeplinks

    async def __aenter__(self) -> Self:
        """Enter the context manager, create and inject a new session."""
        self._session = self._session_factory()

        self.users._session = self._session
        self.bans._session = self._session
        self.admins._session = self._session
        self.subscribers._session = self._session
        self.deeplinks._session = self._session

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the context manager, committing or rolling back."""
        if self._session:
            if exc_type:
                await self.rollback()
            else:
                await self.commit()
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        """Commit the changes."""
        if self._session:
            await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the changes."""
        if self._session:
            await self._session.rollback()
