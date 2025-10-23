from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import DeeplinkAction
from bot.database.repositories.deeplink_repository import DeeplinkRepository
from bot.models import Deeplink


@pytest.fixture(name="engine")
def engine_fixture() -> AsyncEngine:
    """Fixture for an in-memory SQLite engine."""
    return create_async_engine("sqlite+aiosqlite:///:memory:")


@pytest.fixture(name="session")
async def session_fixture(
    engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Fixture for an asynchronous session with a clean database."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine) as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest.fixture
def deeplink_repository(session: AsyncSession) -> DeeplinkRepository:
    """Fixture for a DeeplinkRepository instance."""
    return DeeplinkRepository(session)


@pytest.mark.asyncio
async def test_create_deeplink(
    deeplink_repository: DeeplinkRepository, session: AsyncSession
) -> None:
    """Test creating a new deeplink."""
    action = DeeplinkAction.SUBSCRIBE
    ttl_seconds = 300
    payload = "test_payload"
    expected_telegram_id = 123

    with patch("secrets.token_urlsafe", return_value="mock_token"):
        deeplink = await deeplink_repository.create(
            action=action,
            ttl_seconds=ttl_seconds,
            payload=payload,
            expected_telegram_id=expected_telegram_id,
        )
        await session.commit()
        await session.refresh(deeplink)

    assert deeplink.token == "mock_token"
    assert deeplink.action == action
    assert deeplink.payload == payload
    assert deeplink.expected_telegram_id == expected_telegram_id
    assert (
        (datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=ttl_seconds))
        - deeplink.expiry_time
    ).total_seconds() < 5  # Allow for small time difference


@pytest.mark.asyncio
async def test_resolve_token_valid_and_not_expired(
    deeplink_repository: DeeplinkRepository, session: AsyncSession
) -> None:
    """Test resolving a valid and not expired token."""
    token = "valid_token"
    expiry_time = datetime.now(UTC) + timedelta(minutes=5)
    deeplink_obj = Deeplink(
        token=token, action=DeeplinkAction.SUBSCRIBE, expiry_time=expiry_time
    )
    session.add(deeplink_obj)
    await session.commit()
    session.expunge_all()

    resolved_deeplink = await deeplink_repository.resolve_token(token)
    assert resolved_deeplink is not None
    assert resolved_deeplink.token == token


@pytest.mark.asyncio
async def test_resolve_token_expired(
    deeplink_repository: DeeplinkRepository, session: AsyncSession
) -> None:
    """Test resolving an expired token."""
    token = "expired_token"
    expiry_time = datetime.now(UTC) - timedelta(minutes=5)  # 5 minutes in the past
    deeplink_obj = Deeplink(
        token=token, action=DeeplinkAction.SUBSCRIBE, expiry_time=expiry_time
    )
    session.add(deeplink_obj)
    await session.commit()
    session.expunge_all()

    resolved_deeplink = await deeplink_repository.resolve_token(token)
    assert resolved_deeplink is None

    # Verify it was deleted from the database
    deleted_deeplink = await session.get(Deeplink, token)
    assert deleted_deeplink is None


@pytest.mark.asyncio
async def test_resolve_token_not_found(
    deeplink_repository: DeeplinkRepository,
) -> None:
    """Test resolving a non-existent token."""
    token = "non_existent_token"
    resolved_deeplink = await deeplink_repository.resolve_token(token)
    assert resolved_deeplink is None
