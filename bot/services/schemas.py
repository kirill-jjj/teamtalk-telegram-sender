"""Pydantic schemas for service layer inputs and outputs (DTOs)."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from bot.models import UserSettings


class UserAccountInfo(BaseModel):
    """A simple DTO for TeamTalk user account information."""

    username: str


class SubscriberInfo(BaseModel):
    """Pydantic model for subscriber information for display purposes."""

    telegram_id: int
    display_name: str
    teamtalk_username: str | None = None


T = TypeVar("T")


class PaginatedResult(BaseModel, Generic[T]):
    """Represents a paginated list of items."""

    items: list[T]
    total_items: int
    total_pages: int
    current_page: int


class OperationResult(BaseModel):
    """Represents a structured result for service operations."""

    success: bool
    message_key: str
    message_args: dict[str, Any] | None = Field(default=None)
    user_settings: UserSettings | None = Field(default=None)
    long_message: str | None = Field(default=None)


class BatchOperationResult(BaseModel):
    """Represents the result of a batch operation."""

    successful_ids: list[int] = Field(default_factory=list)
    failed_ids: list[int] = Field(default_factory=list)


class MuteListViewData(BaseModel):
    """A DTO for data required to render a mute list view."""

    items: list[str]
    title: str
    empty_list_text: str
