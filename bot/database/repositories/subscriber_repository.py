"""Repository for managing subscribed users."""

from sqlmodel import select

from bot.database.repositories.base import BaseRepository
from bot.models import SubscribedUser


class SubscriberRepository(BaseRepository[SubscribedUser]):
    """Repository for managing SubscribedUsers."""

    def __init__(self) -> None:
        """Initializes the subscriber repository."""
        super().__init__(SubscribedUser)

    async def get_all_ids(self) -> list[int]:
        """Retrieves the Telegram IDs of all subscribers.

        Returns:
            A list of all subscriber Telegram IDs.
        """
        statement = select(SubscribedUser.telegram_id)
        result = await self._session.exec(statement)
        return list(result.all())
