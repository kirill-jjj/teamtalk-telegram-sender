"""Pydantic schemas for service layer inputs and outputs (DTOs)."""

from typing import Any

from pydantic import BaseModel, Field

from bot.models import UserSettings


class UserAccountInfo(BaseModel):
    """A simple DTO for TeamTalk user account information."""

    username: str


class OperationResult(BaseModel):
    """Represents a structured result for service operations."""

    success: bool
    message_key: str
    message_args: dict[str, Any] | None = Field(default=None)
    user_settings: UserSettings | None = Field(default=None)
    long_message: str | None = Field(default=None)
