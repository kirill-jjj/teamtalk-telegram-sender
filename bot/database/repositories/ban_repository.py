"""Repository for managing ban list entries."""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.repositories.base import BaseRepository
from bot.models import BanList


class BanRepository(BaseRepository[BanList]):
    """Repository for managing BanList entries."""

    def __init__(self, session: AsyncSession) -> None:
        """Initializes the ban repository."""
        super().__init__(session, BanList)

    async def add_ban(
        self,
        telegram_id: int | None = None,
        teamtalk_username: str | None = None,
        reason: str | None = None,
    ) -> BanList:
        """Adds a new entry to the ban list.

        Args:
            telegram_id: The Telegram ID to ban.
            teamtalk_username: The TeamTalk username to ban.
            reason: The reason for the ban.

        Returns:
            The created BanList instance.
        """
        if not telegram_id and not teamtalk_username:
            raise ValueError("Either telegram_id or teamtalk_username must be provided.")
        ban_entry = BanList(
            telegram_id=telegram_id,
            teamtalk_username=teamtalk_username,
            ban_reason=reason,
        )
        await self.add(ban_entry)
        return ban_entry

    async def is_telegram_id_banned(self, telegram_id: int) -> bool:
        """Checks if a Telegram ID is in the ban list.

        Args:
            telegram_id: The Telegram ID to check.

        Returns:
            True if the ID is banned, False otherwise.
        """
        statement = select(BanList).where(BanList.telegram_id == telegram_id)
        result = await self._session.exec(statement)
        return result.first() is not None

    async def is_teamtalk_username_banned(self, teamtalk_username: str) -> bool:
        """Checks if a TeamTalk username is in the ban list.

        Args:
            teamtalk_username: The TeamTalk username to check.

        Returns:
            True if the username is banned, False otherwise.
        """
        statement = select(BanList).where(BanList.teamtalk_username == teamtalk_username)
        result = await self._session.exec(statement)
        return result.first() is not None

    async def get_by_telegram_id(self, telegram_id: int) -> list[BanList]:
        """Retrieves all ban entries for a given Telegram ID.

        Args:
            telegram_id: The Telegram ID to search for.

        Returns:
            A list of matching BanList entries.
        """
        statement = select(BanList).where(BanList.telegram_id == telegram_id)
        result = await self._session.exec(statement)
        return list(result.all())

    async def get_by_teamtalk_username(self, teamtalk_username: str) -> list[BanList]:
        """Retrieves all ban entries for a given TeamTalk username.

        Args:
            teamtalk_username: The TeamTalk username to search for.

        Returns:
            A list of matching BanList entries.
        """
        statement = select(BanList).where(BanList.teamtalk_username == teamtalk_username)
        result = await self._session.exec(statement)
        return list(result.all())

    async def remove_by_telegram_id(self, telegram_id: int) -> None:
        """Removes all ban entries associated with a Telegram ID.

        Args:
            telegram_id: The Telegram ID whose ban entries should be removed.
        """
        entries_to_delete = await self.get_by_telegram_id(telegram_id)
        for entry in entries_to_delete:
            await self._session.delete(entry)
        await self._session.flush()
