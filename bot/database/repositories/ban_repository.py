"""Repository for managing ban list entries."""

from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.models import BanList
from bot.database.repositories.base import BaseRepository


class BanRepository(BaseRepository[BanList]):
    """Repository for managing BanList entries."""

    def __init__(self, session: AsyncSession) -> None:
        """Initializes the ban repository."""
        super().__init__(BanList, session)

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
            raise ValueError
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
        statement = select(func.count()).where(BanList.telegram_id == telegram_id)
        result = await self._session.exec(statement)
        return result.one() > 0

    async def is_teamtalk_username_banned(self, teamtalk_username: str) -> bool:
        """Checks if a TeamTalk username is in the ban list.

        Args:
            teamtalk_username: The TeamTalk username to check.

        Returns:
            True if the username is banned, False otherwise.
        """
        statement = select(func.count()).where(
            BanList.teamtalk_username == teamtalk_username
        )
        result = await self._session.exec(statement)
        return result.one() > 0

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
        statement = select(BanList).where(
            BanList.teamtalk_username == teamtalk_username
        )
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

    async def remove_by_teamtalk_username(self, teamtalk_username: str) -> None:
        """Removes all ban entries associated with a TeamTalk username.

        Args:
            teamtalk_username: The TeamTalk username whose ban entries should be
                removed.
        """
        entries_to_delete = await self.get_by_teamtalk_username(teamtalk_username)
        for entry in entries_to_delete:
            await self._session.delete(entry)
        await self._session.flush()

    async def count_with_telegram_id(self) -> int:
        """Counts all ban entries that have a Telegram ID."""
        statement = (
            select(func.count(BanList.id))  # type: ignore[arg-type]
            .select_from(self._model)
            .where(BanList.telegram_id != None)  # noqa: E711
        )
        result = await self._session.exec(statement)
        count = result.one_or_none()
        return count if count is not None else 0

    async def get_paginated_with_telegram_id(
        self, offset: int, limit: int
    ) -> list[BanList]:
        """Retrieves a paginated list of ban entries that have a Telegram ID."""
        statement = (
            select(self._model)
            .where(BanList.telegram_id != None)  # noqa: E711
            .order_by(BanList.telegram_id)  # type: ignore[arg-type]
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.exec(statement)
        return list(result.all())
