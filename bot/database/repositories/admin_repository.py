"""Repository for managing Admin users."""

from sqlmodel import select

from bot.database.repositories.base import BaseRepository
from bot.models import Admin


class AdminRepository(BaseRepository[Admin]):
    """Repository for managing Admins."""

    def __init__(self) -> None:
        """Initializes the admin repository."""
        super().__init__(Admin)

    async def get_all_ids(self) -> list[int]:
        """Retrieves the Telegram IDs of all admins.

        Returns:
            A list of all admin Telegram IDs.
        """
        statement = select(Admin.telegram_id)
        result = await self._session.exec(statement)
        return list(result.all())
