"""Repository for managing Deeplink objects."""

import datetime as dt
from datetime import datetime, timedelta
import secrets

from sqlmodel import col, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.constants import DEEPLINK_TOKEN_LENGTH_BYTES
from bot.core.enums import DeeplinkAction
from bot.database.models import Deeplink
from bot.database.repositories.base import BaseRepository


class DeeplinkRepository(BaseRepository[Deeplink]):
    """Repository for managing Deeplinks."""

    def __init__(self, session: AsyncSession) -> None:
        """Initializes the deeplink repository."""
        super().__init__(Deeplink, session)

    async def create(
        self,
        action: DeeplinkAction,
        ttl_seconds: int,
        payload: str | None = None,
        expected_telegram_id: int | None = None,
    ) -> Deeplink:
        """Creates a new deeplink token and stores it in the database.

        Args:
            action: The DeeplinkAction to perform.
            ttl_seconds: Time-to-live for the deeplink in seconds.
            payload: Optional payload associated with the deeplink.
            expected_telegram_id: Optional Telegram ID expected to use this deeplink.

        Returns:
            The created Deeplink object.
        """
        token_str = secrets.token_urlsafe(DEEPLINK_TOKEN_LENGTH_BYTES)
        expiry_time = datetime.now(dt.UTC) + timedelta(seconds=ttl_seconds)
        deeplink = Deeplink(
            token=token_str,
            action=action,
            payload=payload,
            expected_telegram_id=expected_telegram_id,
            expiry_time=expiry_time,
        )
        await self.add(deeplink)
        return deeplink

    async def resolve_token(self, token: str) -> Deeplink | None:
        """Retrieves a deeplink by its token, deleting it if it has expired.

        Args:
            token: The deeplink token string.

        Returns:
            The Deeplink object if found and not expired, otherwise None.
        """
        deeplink = await self.get_by_id(token)
        if deeplink:
            # Assume expiry_time from DB is naive but represents UTC. Make it aware.
            loaded_expiry_time_utc = deeplink.expiry_time.replace(tzinfo=dt.UTC)
            if loaded_expiry_time_utc < datetime.now(dt.UTC):
                await self.delete(deeplink)
                return None
        return deeplink

    async def delete_expired(self) -> int:
        """Deletes all expired deeplinks from the database.

        Returns:
            The number of deleted deeplinks.
        """
        now = datetime.now(dt.UTC)
        statement = delete(self._model).where(col(self._model.expiry_time) < now)
        result = await self._session.exec(statement)
        deleted_count = result.rowcount
        await self._session.flush()
        return deleted_count
