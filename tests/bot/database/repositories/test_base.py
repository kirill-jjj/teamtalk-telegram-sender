from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.database.repositories.base import BaseRepository


class DummyModel(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def base_repository(mock_session: AsyncMock) -> BaseRepository[DummyModel]:
    return BaseRepository(model=DummyModel, session=mock_session)


@pytest.mark.asyncio
async def test_get_by_id(
    base_repository: BaseRepository[DummyModel], mock_session: AsyncMock
) -> None:
    expected_model = DummyModel(id=1, name="Test")
    mock_session.get.return_value = expected_model

    result = await base_repository.get_by_id(1)

    mock_session.get.assert_called_once_with(DummyModel, 1)
    assert result == expected_model


@pytest.mark.asyncio
async def test_get_all(
    base_repository: BaseRepository[DummyModel], mock_session: AsyncMock
) -> None:
    expected_models = [DummyModel(id=1, name="Test1"), DummyModel(id=2, name="Test2")]
    mock_exec_result = MagicMock()
    mock_exec_result.all.return_value = expected_models
    mock_session.exec.return_value = mock_exec_result

    result = await base_repository.get_all()

    mock_session.exec.assert_called_once()
    # We can't directly assert the statement object, but we can check the call
    # For a more robust test, we might inspect the arguments passed to exec
    assert result == expected_models


@pytest.mark.asyncio
async def test_add(
    base_repository: BaseRepository[DummyModel], mock_session: AsyncMock
) -> None:
    new_model = DummyModel(name="New Test")

    await base_repository.add(new_model)

    mock_session.add.assert_called_once_with(new_model)
    mock_session.flush.assert_called_once()
    mock_session.refresh.assert_called_once_with(new_model)


@pytest.mark.asyncio
async def test_delete(
    base_repository: BaseRepository[DummyModel], mock_session: AsyncMock
) -> None:
    model_to_delete = DummyModel(id=1, name="Delete Me")

    await base_repository.delete(model_to_delete)

    mock_session.delete.assert_called_once_with(model_to_delete)
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_get_paginated(
    base_repository: BaseRepository[DummyModel], mock_session: AsyncMock
) -> None:
    expected_models = [DummyModel(id=1, name="Page1")]
    mock_exec_result = MagicMock()
    mock_exec_result.all.return_value = expected_models
    mock_session.exec.return_value = mock_exec_result

    # Test without order_by
    result = await base_repository.get_paginated(offset=0, limit=1)
    mock_session.exec.assert_called_once()
    assert result == expected_models
    mock_session.exec.reset_mock()  # Reset mock for next test

    # Test with order_by
    result = await base_repository.get_paginated(
        offset=0, limit=1, order_by=DummyModel.name
    )
    mock_session.exec.assert_called_once()
    assert result == expected_models


@pytest.mark.asyncio
async def test_count_all(
    base_repository: BaseRepository[DummyModel], mock_session: AsyncMock
) -> None:
    expected_count = 5
    mock_exec_result = MagicMock()
    mock_exec_result.one_or_none.return_value = expected_count
    mock_session.exec.return_value = mock_exec_result

    result = await base_repository.count_all()

    mock_session.exec.assert_called_once()
    assert result == expected_count
