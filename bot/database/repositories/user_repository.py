"""Repository for managing user settings."""

from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.repositories.base import BaseRepository
from bot.models import UserSettings


class UserRepository(BaseRepository[UserSettings]):
    """Repository for managing UserSettings."""

    def __init__(self, session: AsyncSession) -> None:
        """Initializes the user repository."""
        super().__init__(UserSettings, session)

    async def get_by_id(self, pk: int | str) -> UserSettings | None:
        """Get a UserSettings instance by Telegram ID, preloading muted users."""
        statement = (
            select(UserSettings)
            .where(UserSettings.telegram_id == pk)
            .options(selectinload(UserSettings.muted_users_list))  # type: ignore[arg-type]
        )
        result = await self._session.exec(statement)
        return result.first()

    async def get_or_create(
        self, telegram_id: int, defaults: dict[str, Any] | None = None
    ) -> UserSettings:
        """Get or create a UserSettings instance."""
        user_settings = await self.get_by_id(telegram_id)
        if user_settings:
            return user_settings

        defaults = defaults or {}
        user_settings = UserSettings(telegram_id=telegram_id, **defaults)
        self._session.add(user_settings)
        await self._session.flush()
        await self._session.refresh(user_settings, attribute_names=["muted_users_list"])
        return user_settings

    async def save(self, user_settings: UserSettings) -> None:
        """Saves a UserSettings instance (creates or updates)."""
        # If the object is new, it would have been added by get_or_create.
        # If it's existing, it's already attached.
        # So, direct add() here is often redundant and can cause issues.
        # We rely on the session tracking changes to attached objects.
        await self._session.flush()
        await self._session.refresh(user_settings, attribute_names=["muted_users_list"])

    async def get_all(self) -> list[UserSettings]:
        """Retrieves all instances of the model, preloading muted users."""
        statement = select(self._model).options(
            selectinload(UserSettings.muted_users_list)  # type: ignore[arg-type]
        )
        result = await self._session.exec(statement)
        return list(result.all())

    async def get_by_ids(self, telegram_ids: list[int]) -> list[UserSettings]:
        """Retrieves multiple UserSettings instances by their Telegram IDs."""
        statement = (
            select(UserSettings)
            .where(UserSettings.telegram_id.in_(telegram_ids))  # type: ignore[attr-defined]
            .options(selectinload(UserSettings.muted_users_list))  # type: ignore[arg-type]
        )
        result = await self._session.exec(statement)
        return list(result.all())
