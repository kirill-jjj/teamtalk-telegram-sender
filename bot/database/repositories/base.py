"""Base class for data repositories."""

import logging
from typing import Any, Generic, TypeVar

from sqlalchemy import Column
from sqlmodel import SQLModel, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

Model = TypeVar("Model", bound=SQLModel)


class BaseRepository(Generic[Model]):
    """A base class for data repositories.

    A generic repository for common CRUD operations on a SQLModel model.
    This class is designed to be subclassed by specific repositories that handle
    individual models.
    """

    def __init__(self, model: type[Model], session: AsyncSession) -> None:
        """Initializes the repository.

        Args:
            model: The SQLModel class that this repository will manage.
            session: The AsyncSession to use for database operations.
        """
        self._session = session
        self._model = model

    async def get_by_id(self, pk: int | str) -> Model | None:
        """Retrieves a model instance by its primary key.

        Args:
            pk: The primary key of the model instance to retrieve.

        Returns:
            The model instance if found, otherwise None.
        """
        logger.debug("Getting %s by primary key %s", self._model.__name__, pk)
        return await self._session.get(self._model, pk)

    async def get_all(self) -> list[Model]:
        """Retrieves all instances of the model.

        Returns:
            A list of all model instances.
        """
        logger.debug("Getting all instances of %s", self._model.__name__)
        statement = select(self._model)
        result = await self._session.exec(statement)
        return list(result.all())

    async def add(self, model_instance: Model) -> None:
        """Adds a new model instance to the session.

        Note: This method does not commit the session. The session is managed
        at a higher level (e.g., using a Unit of Work pattern).

        Args:
            model_instance: The model instance to add.
        """
        logger.debug("Adding new %s: %s", self._model.__name__, model_instance)
        self._session.add(model_instance)
        await self._session.flush()
        await self._session.refresh(model_instance)

    async def delete(self, model_instance: Model) -> None:
        """Deletes a model instance from the session.

        Note: This method does not commit the session. The session is managed
        at a higher level.

        Args:
            model_instance: The model instance to delete.
        """
        logger.debug("Deleting %s: %s", self._model.__name__, model_instance)
        await self._session.delete(model_instance)
        await self._session.flush()

    async def get_paginated(
        self, offset: int, limit: int, order_by: str | Column[Any] | None = None
    ) -> list[Model]:
        """Retrieves a paginated list of model instances."""
        logger.debug(
            "Getting paginated %s with offset=%s, limit=%s",
            self._model.__name__,
            offset,
            limit,
        )
        statement = select(self._model)
        if order_by is not None:
            statement = statement.order_by(order_by)

        statement = statement.offset(offset).limit(limit)
        result = await self._session.exec(statement)
        return list(result.all())

    async def count_all(self) -> int:
        """Counts all instances of the model."""
        logger.debug("Counting all instances of %s", self._model.__name__)
        statement = select(func.count()).select_from(self._model)
        result = await self._session.exec(statement)
        count = result.one_or_none()
        return count if count is not None else 0
