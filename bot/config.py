"""Configuration models for the bot application."""

import os
from typing import Literal

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# Type for gender, can be expanded if needed
GenderType = Literal["male", "female", "neutral"]


class GeneralSettings(BaseSettings):
    """General bot settings."""

    default_lang: str = Field("en", description="Default language for bot messages.")
    gender: GenderType = Field(
        "neutral", description="Gender for bot's persona in localized messages."
    )
    admin_username: str | None = Field(
        None, description="Optional admin username for display/identification."
    )


class DatabaseSettings(BaseSettings):
    """Database-specific settings."""

    db_file: str = Field("bot_data.db", description="Path to the SQLite database file.")


class TelegramSettings(BaseSettings):
    """Telegram-specific settings."""

    event_token: str = Field(
        description="Main Telegram Bot API token for receiving events."
    )
    message_token: str = Field(
        description="Telegram Bot API token for sending messages (can be same as event_token)."
    )
    admin_chat_id: int = Field(
        description="Telegram Chat ID of the administrator for notifications."
    )


class TeamTalkSettings(BaseSettings):
    """TeamTalk-specific settings."""

    host_name: str = Field(
        "teamtalk.example.com", description="TeamTalk server address."
    )
    port: int = Field(10333, description="TeamTalk server port.")
    encrypted: bool = Field(
        default=False, description="Whether the TeamTalk connection is encrypted."
    )
    user_name: str = Field("BotUser", description="Bot's username on TeamTalk.")
    password: str = Field(..., description="Bot's password on TeamTalk.")
    channel: str = Field(
        "/Root/Public Channel", description="Full path to TeamTalk channel."
    )
    channel_password: str | None = Field(
        None, description="Password for the TeamTalk channel, if any."
    )
    nick_name: str = Field("NotifierBot", description="Bot's nickname on TeamTalk.")
    status_text: str = Field(
        "Forwarding notifications to Telegram",
        description="Bot's status message on TeamTalk.",
    )
    client_name: str = Field(
        "TTTelegramBotV1", description="Client name reported to TeamTalk server."
    )
    server_name: str | None = Field(
        None, description="Optional name for the TeamTalk server (for display)."
    )
    global_ignore_usernames: list[str] = Field(
        default_factory=list,
        description="List of TeamTalk usernames to ignore globally.",
    )


class OperationalParameters(BaseSettings):
    """Settings for operational parameters like TTLs and retry intervals."""

    deeplink_ttl_seconds: int = Field(300, description="TTL for deeplinks in seconds.")
    tt_reconnect_retry_seconds: int = Field(
        15, description="Retry interval for TeamTalk connection."
    )
    tt_reconnect_check_interval_seconds: int = Field(
        10, description="Check interval for TeamTalk connection status."
    )
    online_users_cache_sync_interval_seconds: int = Field(
        300, description="Sync interval for online TeamTalk users cache."
    )


class Settings(BaseSettings):
    """Main application settings class.

    Loads configuration from a TOML file, with environment variable overrides.
    """

    general: GeneralSettings
    database: DatabaseSettings
    telegram: TelegramSettings
    teamtalk: TeamTalkSettings
    operational_parameters: OperationalParameters = Field(
        default_factory=OperationalParameters
    )

    model_config = SettingsConfigDict(
        toml_file=os.environ.get("APP_CONFIG_PATH", "config.toml"),
        env_prefix="TT_SENDER_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Customize the sources and their order for loading settings."""
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )
