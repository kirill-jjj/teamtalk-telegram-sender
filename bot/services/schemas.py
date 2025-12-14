"""Pydantic schemas for service layer inputs and outputs (DTOs)."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from bot.core.enums import DeeplinkAction
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


class MuteListDisplayDTO(BaseModel):
    """DTO for displaying a user's mute list."""

    telegram_id: int
    display_name: str
    mute_list_mode: MuteListMode
    muted_usernames: list[str]
    language_code: str


class ManageMutedMenuDTO(BaseModel):
    """DTO for data required to render the manage muted users menu."""

    mute_list_mode: MuteListMode
    not_on_online_enabled: bool


class RecipientDTO(BaseModel):
    """DTO for a notification recipient."""

    telegram_id: int
    language_code: str | None


class TeamTalkFetchResult(BaseModel, Generic[T]):
    """Result of a fetch operation from TeamTalk service."""

    items: list[T] = Field(default_factory=list)
    error_message: str | None = None
    server_name: str | None = None  # Optional, primarily for online users fetch


class DeeplinkDTO(BaseModel):
    """Data Transfer Object for a deeplink."""

    token: str
    action: DeeplinkAction
    payload: str | None = None
