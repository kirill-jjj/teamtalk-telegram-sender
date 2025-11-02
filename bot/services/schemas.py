"""Pydantic schemas for service layer inputs and outputs (DTOs)."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from bot.database.models import UserSettings
from bot.database.types import MuteListMode, NotificationSetting


class SettingsViewDTO(BaseModel):
    """DTO for displaying user settings in the UI."""

    telegram_id: int
    language_code: str
    notification_settings: NotificationSetting
    mute_list_mode: MuteListMode
    not_on_online_enabled: bool
    not_on_online_confirmed: bool
    teamtalk_username: str | None
    muted_users_count: int


class UserDTO(BaseModel):
    """Data Transfer Object for a user, used for decoupling."""

    id: int
    nickname: str
    channel_name: str


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


class AdminManagementResult(BaseModel):
    """Represents the result of an admin management operation."""

    add_result: BatchOperationResult
    remove_result: BatchOperationResult
    error_messages: list[str]


class MuteListViewData(BaseModel):
    """A DTO for data required to render a mute list view."""

    items: list[str]
    title: str
    empty_list_text: str


class AllAccountsViewData(BaseModel):
    """A DTO for data required to render the all server accounts list view."""

    accounts: list[UserAccountInfo]
    title: str
    empty_list_text: str


class AccountManagementData(BaseModel):
    """A DTO for data required for account management view."""

    current_tt_username: str | None


class SubscriberView(BaseModel):
    """DTO for subscriber data including settings and display name."""

    telegram_id: int
    language_code: str
    notification_settings: NotificationSetting
    mute_list_mode: MuteListMode
    not_on_online_enabled: bool
    not_on_online_confirmed: bool
    teamtalk_username: str | None
    muted_users_count: int
    display_name: str


class ModerationViewData(BaseModel):
    """A DTO for data required to render a moderation view."""

    users: list[UserDTO]
    server_name: str
    error_message: str | None = None
