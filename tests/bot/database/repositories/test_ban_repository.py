from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.models import BanList
from bot.database.repositories.ban_repository import BanRepository


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
def ban_repository(session: AsyncSession) -> BanRepository:
    """Fixture for a BanRepository instance."""
    return BanRepository(session)


@pytest.mark.asyncio
async def test_add_ban_by_telegram_id(ban_repository: BanRepository) -> None:
    """Test adding a ban entry using only Telegram ID."""
    telegram_id = 123
    ban_entry = await ban_repository.add_ban(telegram_id=telegram_id)
    assert ban_entry.telegram_id == telegram_id
    assert ban_entry.teamtalk_username is None
    assert ban_entry.ban_reason is None
    assert ban_entry.banned_at is not None


@pytest.mark.asyncio
async def test_add_ban_by_teamtalk_username(ban_repository: BanRepository) -> None:
    """Test adding a ban entry using only TeamTalk username."""
    teamtalk_username = "test_user"
    ban_entry = await ban_repository.add_ban(teamtalk_username=teamtalk_username)
    assert ban_entry.telegram_id is None
    assert ban_entry.teamtalk_username == teamtalk_username
    assert ban_entry.ban_reason is None


@pytest.mark.asyncio
async def test_add_ban_with_both_identifiers_and_reason(
    ban_repository: BanRepository,
) -> None:
    """Test adding a ban entry with both identifiers and a reason."""
    telegram_id = 456
    teamtalk_username = "another_user"
    reason = "Spamming"
    ban_entry = await ban_repository.add_ban(
        telegram_id=telegram_id, teamtalk_username=teamtalk_username, reason=reason
    )
    assert ban_entry.telegram_id == telegram_id
    assert ban_entry.teamtalk_username == teamtalk_username
    assert ban_entry.ban_reason == reason


@pytest.mark.asyncio
async def test_add_ban_no_identifier_raises_error(
    ban_repository: BanRepository,
) -> None:
    """Test adding a ban entry without any identifier raises ValueError."""
    with pytest.raises(ValueError, match=r"^$"):
        await ban_repository.add_ban()


@pytest.mark.asyncio
async def test_is_telegram_id_banned(
    ban_repository: BanRepository, session: AsyncSession
) -> None:
    """Test checking if a Telegram ID is banned."""
    telegram_id = 789
    session.add(BanList(telegram_id=telegram_id))
    await session.commit()

    assert await ban_repository.is_telegram_id_banned(telegram_id) is True
    assert await ban_repository.is_telegram_id_banned(999) is False


@pytest.mark.asyncio
async def test_is_teamtalk_username_banned(
    ban_repository: BanRepository, session: AsyncSession
) -> None:
    """Test checking if a TeamTalk username is banned."""
    teamtalk_username = "banned_tt_user"
    session.add(BanList(teamtalk_username=teamtalk_username))
    await session.commit()

    assert await ban_repository.is_teamtalk_username_banned(teamtalk_username) is True
    assert await ban_repository.is_teamtalk_username_banned("non_existent") is False


@pytest.mark.asyncio
async def test_get_by_telegram_id(
    ban_repository: BanRepository, session: AsyncSession
) -> None:
    """Test retrieving ban entries by Telegram ID."""
    telegram_id = 101
    session.add(BanList(telegram_id=telegram_id, reason="Test1"))
    session.add(BanList(telegram_id=telegram_id, reason="Test2"))
    session.add(BanList(teamtalk_username="other_tt"))
    await session.commit()

    bans = await ban_repository.get_by_telegram_id(telegram_id)
    assert len(bans) == 2
    assert all(b.telegram_id == telegram_id for b in bans)


@pytest.mark.asyncio
async def test_get_by_teamtalk_username(
    ban_repository: BanRepository, session: AsyncSession
) -> None:
    """Test retrieving ban entries by TeamTalk username."""
    teamtalk_username = "tt_banned"
    session.add(BanList(teamtalk_username=teamtalk_username, reason="Reason1"))
    session.add(BanList(teamtalk_username=teamtalk_username, reason="Reason2"))
    session.add(BanList(telegram_id=202))
    await session.commit()

    bans = await ban_repository.get_by_teamtalk_username(teamtalk_username)
    assert len(bans) == 2
    assert all(b.teamtalk_username == teamtalk_username for b in bans)


@pytest.mark.asyncio
async def test_remove_by_telegram_id(
    ban_repository: BanRepository, session: AsyncSession
) -> None:
    """Test removing ban entries by Telegram ID."""
    telegram_id = 303
    session.add(BanList(telegram_id=telegram_id))
    session.add(BanList(telegram_id=telegram_id, teamtalk_username="linked_tt"))
    session.add(BanList(telegram_id=404))
    await session.commit()

    await ban_repository.remove_by_telegram_id(telegram_id)
    await session.commit()

    assert await ban_repository.is_telegram_id_banned(telegram_id) is False
    assert (
        await ban_repository.is_telegram_id_banned(404) is True
    )  # Other bans unaffected


@pytest.mark.asyncio
async def test_remove_by_teamtalk_username(
    ban_repository: BanRepository, session: AsyncSession
) -> None:
    """Test removing ban entries by TeamTalk username."""
    teamtalk_username = "tt_to_remove"
    session.add(BanList(teamtalk_username=teamtalk_username))
    session.add(BanList(telegram_id=505, teamtalk_username=teamtalk_username))
    session.add(BanList(teamtalk_username="other_tt"))
    await session.commit()

    await ban_repository.remove_by_teamtalk_username(teamtalk_username)
    await session.commit()

    assert await ban_repository.is_teamtalk_username_banned(teamtalk_username) is False
    assert (
        await ban_repository.is_telegram_id_banned(505) is False
    )  # Other bans unaffected


@pytest.mark.asyncio
async def test_count_with_telegram_id(
    ban_repository: BanRepository, session: AsyncSession
) -> None:
    """Test counting ban entries with a Telegram ID."""
    ban1 = BanList(telegram_id=1)
    ban2 = BanList(telegram_id=2, teamtalk_username="tt1")
    ban3 = BanList(telegram_id=None, teamtalk_username="tt2")  # No telegram_id
    session.add(ban1)
    session.add(ban2)
    session.add(ban3)
    await session.flush()
    await session.refresh(ban1)
    await session.refresh(ban2)
    await session.refresh(ban3)
    await session.commit()

    # Debugging: Raw SQL query to check actual DB state

    result_not_null = await session.exec(
        text("SELECT COUNT(*) FROM ban_list WHERE telegram_id IS NOT NULL")
    )
    raw_count_not_null = result_not_null.scalar_one()
    assert raw_count_not_null == 2

    result_is_null = await session.exec(
        text("SELECT COUNT(*) FROM ban_list WHERE telegram_id IS NULL")
    )
    raw_count_is_null = result_is_null.scalar_one()
    assert raw_count_is_null == 1

    count = await ban_repository.count_with_telegram_id()
    assert count == 2


@pytest.mark.asyncio
async def test_get_paginated_with_telegram_id(
    ban_repository: BanRepository, session: AsyncSession
) -> None:
    """Test retrieving paginated ban entries with a Telegram ID."""
    bans_to_add = []
    for i in range(1, 6):
        ban = BanList(telegram_id=i)
        session.add(ban)
        bans_to_add.append(ban)
    ban_tt_only = BanList(telegram_id=None, teamtalk_username="tt_only")
    session.add(ban_tt_only)
    bans_to_add.append(ban_tt_only)

    await session.flush()
    for ban_obj in bans_to_add:
        await session.refresh(ban_obj)
    await session.commit()

    paginated_bans = await ban_repository.get_paginated_with_telegram_id(
        offset=0, limit=2
    )
    assert len(paginated_bans) == 2
    assert {b.telegram_id for b in paginated_bans} == {1, 2}

    paginated_bans = await ban_repository.get_paginated_with_telegram_id(
        offset=2, limit=2
    )
    assert len(paginated_bans) == 2
    assert {b.telegram_id for b in paginated_bans} == {3, 4}

    paginated_bans = await ban_repository.get_paginated_with_telegram_id(
        offset=4, limit=2
    )
    assert len(paginated_bans) == 1
    assert {b.telegram_id for b in paginated_bans} == {5}

    paginated_bans = await ban_repository.get_paginated_with_telegram_id(
        offset=5, limit=2
    )
    assert len(paginated_bans) == 0
