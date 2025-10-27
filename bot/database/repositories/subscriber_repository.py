"""Repository for managing subscribed users."""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.models import SubscribedUser
from bot.database.repositories.base import BaseRepository


class SubscriberRepository(BaseRepository[SubscribedUser]):
    """Repository for managing SubscribedUsers."""

    def __init__(self, session: AsyncSession) -> None:
        """Initializes the subscriber repository."""
        super().__init__(SubscribedUser, session)

    async def get_all_ids(self) -> list[int]:
        """Retrieves the Telegram IDs of all subscribers.

        Returns:
            A list of all subscriber Telegram IDs.
        """
        statement = select(SubscribedUser.telegram_id)
        result = await self._session.exec(statement)
        return list(result.all())
