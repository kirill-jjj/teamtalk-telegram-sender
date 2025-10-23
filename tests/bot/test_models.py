"""Tests for the SQLModel definitions in bot/models.py."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import selectinload
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.core.enums import DeeplinkAction
from bot.models import (
    Admin,
    BanList,
    Deeplink,
    MutedUser,
    MuteListMode,
    NotificationSetting,
    SubscribedUser,
    UserSettings,
)


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


@pytest.mark.asyncio
async def test_user_settings_defaults(session: AsyncSession) -> None:
    """Test default values for UserSettings."""
    user = UserSettings(telegram_id=1, language_code="en")
    session.add(user)
    await session.commit()

    retrieved_user = await session.get(UserSettings, 1)
    assert retrieved_user.notification_settings == NotificationSetting.ALL
    assert retrieved_user.mute_list_mode == MuteListMode.blacklist
    assert retrieved_user.not_on_online_enabled is False
    assert retrieved_user.not_on_online_confirmed is False
    assert retrieved_user.teamtalk_username is None


@pytest.mark.asyncio
async def test_user_settings_notification_constraint(session: AsyncSession) -> None:
    """Test notification_settings CheckConstraint."""
    user = UserSettings(telegram_id=1, language_code="en")
    user.notification_settings = "invalid_setting"  # type: ignore[assignment]
    session.add(user)
    with pytest.raises(IntegrityError, match="ck_user_settings_notification_valid"):
        await session.commit()


@pytest.mark.asyncio
async def test_user_settings_mute_mode_constraint(session: AsyncSession) -> None:
    """Test mute_list_mode CheckConstraint."""
    user = UserSettings(telegram_id=1, language_code="en")
    user.mute_list_mode = "invalid_mode"  # type: ignore[assignment]
    session.add(user)
    with pytest.raises(IntegrityError, match="ck_user_settings_mute_mode_valid"):
        await session.commit()


@pytest.mark.asyncio
async def test_muted_user_relationship_and_cascade_delete(
    session: AsyncSession,
) -> None:
    """Test MutedUser relationship and cascade delete."""
    user = UserSettings(telegram_id=1, language_code="en")
    muted1 = MutedUser(muted_teamtalk_username="muted1", user_settings=user)
    muted2 = MutedUser(muted_teamtalk_username="muted2", user_settings=user)

    session.add(user)
    session.add(muted1)
    session.add(muted2)
    await session.commit()
    await session.refresh(user)

    retrieved_user = await session.exec(
        select(UserSettings)
        .where(UserSettings.telegram_id == 1)
        .options(selectinload(UserSettings.muted_users_list))
    )
    retrieved_user = retrieved_user.first()
    assert len(retrieved_user.muted_users_list) == 2

    await session.delete(retrieved_user)
    await session.commit()

    assert await session.get(UserSettings, 1) is None
    assert await session.get(MutedUser, muted1.id) is None
    assert await session.get(MutedUser, muted2.id) is None


@pytest.mark.asyncio
async def test_muted_user_unique_constraint(session: AsyncSession) -> None:
    """Test uq_user_muted_username UniqueConstraint."""
    user = UserSettings(telegram_id=1, language_code="en")
    muted1 = MutedUser(muted_teamtalk_username="duplicate", user_settings=user)
    muted2 = MutedUser(muted_teamtalk_username="duplicate", user_settings=user)

    session.add(user)
    session.add(muted1)
    session.add(muted2)
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        await session.commit()


@pytest.mark.asyncio
async def test_subscribed_user_model(session: AsyncSession) -> None:
    """Test SubscribedUser model."""
    sub_user = SubscribedUser(telegram_id=123)
    session.add(sub_user)
    await session.commit()

    retrieved_sub = await session.get(SubscribedUser, 123)
    assert retrieved_sub is not None
    assert retrieved_sub.telegram_id == 123


@pytest.mark.asyncio
async def test_admin_model(session: AsyncSession) -> None:
    """Test Admin model."""
    admin_user = Admin(telegram_id=456)
    session.add(admin_user)
    await session.commit()

    retrieved_admin = await session.get(Admin, 456)
    assert retrieved_admin is not None
    assert retrieved_admin.telegram_id == 456


@pytest.mark.asyncio
async def test_deeplink_model(session: AsyncSession) -> None:
    """Test Deeplink model."""
    expiry = datetime.now(UTC) + timedelta(minutes=5)
    # Make expiry timezone-naive for comparison with SQLite stored datetime
    naive_expiry = expiry.replace(tzinfo=None)
    deeplink = Deeplink(
        token="test_token",
        action=DeeplinkAction.SUBSCRIBE,
        payload="some_payload",
        expected_telegram_id=789,
        expiry_time=expiry,
    )
    session.add(deeplink)
    await session.commit()

    retrieved_deeplink = await session.get(Deeplink, "test_token")
    assert retrieved_deeplink is not None
    assert retrieved_deeplink.action == DeeplinkAction.SUBSCRIBE
    assert retrieved_deeplink.payload == "some_payload"
    assert retrieved_deeplink.expected_telegram_id == 789
    # Compare expiry_time with a small tolerance due to potential precision differences
    assert abs((retrieved_deeplink.expiry_time - naive_expiry).total_seconds()) < 1


@pytest.mark.asyncio
async def test_ban_list_defaults_and_constraint(session: AsyncSession) -> None:
    """Test BanList defaults and ck_ban_list_identifier_not_both_null constraint."""
    # Test default banned_at
    ban_entry = BanList(telegram_id=1)
    session.add(ban_entry)
    await session.commit()
    await session.refresh(ban_entry)

    # Ensure ban_entry.id is populated after commit
    assert ban_entry.id is not None
    retrieved_ban = await session.get(BanList, ban_entry.id)
    assert retrieved_ban.banned_at is not None
    assert (
        datetime.now(UTC).replace(tzinfo=None) - retrieved_ban.banned_at
    ) < timedelta(seconds=5)

    # Test constraint: both None
    invalid_ban = BanList()
    session.add(invalid_ban)
    with pytest.raises(IntegrityError, match="ck_ban_list_identifier_not_both_null"):
        await session.commit()
    await session.rollback()

    # Test constraint: one is None (valid)
    valid_ban_tt = BanList(teamtalk_username="banned_tt")
    session.add(valid_ban_tt)
    await session.commit()
    await session.refresh(valid_ban_tt)

    # Ensure valid_ban_tt.id is populated after commit
    assert valid_ban_tt.id is not None
    retrieved_ban_tt = await session.get(BanList, valid_ban_tt.id)
    assert retrieved_ban_tt.teamtalk_username == "banned_tt"
    assert retrieved_ban_tt.telegram_id is None
