"""Repository for managing user settings."""

from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import NotificationType
from bot.database.models import MutedUser, UserSettings
from bot.database.repositories.base import BaseRepository
from bot.database.types import MuteListMode, NotificationSetting


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
            .options(selectinload(cast("Any", UserSettings.muted_users_list)))
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
            selectinload(cast("Any", UserSettings.muted_users_list))
        )
        result = await self._session.exec(statement)
        return list(result.all())

    async def get_by_ids(self, telegram_ids: list[int]) -> list[UserSettings]:
        """Retrieves multiple UserSettings instances by their Telegram IDs."""
        statement = (
            select(UserSettings)
            .where(col(UserSettings.telegram_id).in_(telegram_ids))
            .options(selectinload(cast("Any", UserSettings.muted_users_list)))
        )
        result = await self._session.exec(statement)
        return list(result.all())

    async def get_by_teamtalk_username(self, username: str) -> UserSettings | None:
        """Get a UserSettings instance by TeamTalk username."""
        statement = (
            select(UserSettings)
            .where(UserSettings.teamtalk_username == username)
            .options(selectinload(cast("Any", UserSettings.muted_users_list)))
        )
        result = await self._session.exec(statement)
        return result.first()

    async def get_notification_recipients(
        self,
        subscriber_ids: list[int],
        username_to_check: str,
        event_type: NotificationType,
    ) -> list[tuple[int, str | None]]:
        """Get a list of notification recipients from the database."""
        if not subscriber_ids:
            return []
        stmt = (
            select(
                UserSettings.telegram_id,
                UserSettings.language_code,
            )
            .join(
                MutedUser,
                sa.and_(
                    col(UserSettings.telegram_id)
                    == MutedUser.user_settings_telegram_id,
                    col(MutedUser.muted_teamtalk_username) == username_to_check,
                ),
                isouter=True,
            )
            .where(
                col(UserSettings.telegram_id).in_(subscriber_ids),
                UserSettings.notification_settings != NotificationSetting.NONE,
            )
        )

        if event_type == NotificationType.JOIN:
            stmt = stmt.where(
                UserSettings.notification_settings != NotificationSetting.JOIN_OFF
            )
        elif event_type == NotificationType.LEAVE:
            stmt = stmt.where(
                UserSettings.notification_settings != NotificationSetting.LEAVE_OFF
            )

        mute_logic = sa.or_(
            sa.and_(
                col(UserSettings.mute_list_mode) == MuteListMode.blacklist.value,
                col(MutedUser.id).is_(None),
            ),
            sa.and_(
                col(UserSettings.mute_list_mode) == MuteListMode.whitelist.value,
                col(MutedUser.id).is_not(None),
            ),
        )
        stmt = stmt.where(mute_logic)

        result = await self._session.execute(stmt)
        return cast("list[tuple[int, str | None]]", result.all())
